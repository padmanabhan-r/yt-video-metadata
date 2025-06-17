import streamlit as st
import pandas as pd
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import os
from datetime import datetime
import re
from io import BytesIO

# Set page config
st.set_page_config(
    page_title="YouTube Channel Content Fetcher",
    page_icon="🎥",
    layout="wide"
)

# Initialize session state
if 'content_df' not in st.session_state:
    st.session_state.content_df = None
if 'channel_info' not in st.session_state:
    st.session_state.channel_info = None

@st.cache_data
def get_youtube_service(api_key):
    """Initialize YouTube API service with caching"""
    try:
        return build('youtube', 'v3', developerKey=api_key)
    except Exception as e:
        st.error(f"Failed to initialize YouTube API service: {str(e)}")
        return None

def extract_channel_id_from_url(url):
    """Extract channel ID from various YouTube URL formats"""
    patterns = [
        r'youtube\.com/channel/([a-zA-Z0-9_-]+)',
        r'youtube\.com/c/([a-zA-Z0-9_-]+)',
        r'youtube\.com/user/([a-zA-Z0-9_-]+)',
        r'youtube\.com/@([a-zA-Z0-9_-]+)'
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1), pattern
    return None, None

def get_channel_id_from_username(youtube, username):
    """Get channel ID from username or handle"""
    try:
        methods = [
            {'part': 'id', 'forUsername': username},
            {'part': 'id', 'forHandle': f'@{username}' if not username.startswith('@') else username}
        ]
        
        for method in methods:
            try:
                response = youtube.channels().list(**method).execute()
                if response['items']:
                    return response['items'][0]['id']
            except:
                continue
        
        search_response = youtube.search().list(
            part='snippet',
            q=username,
            type='channel',
            maxResults=1
        ).execute()
        
        if search_response['items']:
            return search_response['items'][0]['snippet']['channelId']
        
        return None
    except Exception as e:
        st.error(f"Error getting channel ID: {str(e)}")
        return None

def get_channel_info(youtube, channel_id):
    """Get basic channel information"""
    try:
        response = youtube.channels().list(
            part='snippet,statistics,contentDetails',
            id=channel_id
        ).execute()
        
        if not response['items']:
            return None
        
        channel = response['items'][0]
        return {
            'title': channel['snippet']['title'],
            'subscriber_count': channel['statistics'].get('subscriberCount', 'N/A'),
            'video_count': channel['statistics'].get('videoCount', 'N/A'),
            'uploads_playlist_id': channel['contentDetails']['relatedPlaylists']['uploads']
        }
    except Exception as e:
        st.error(f"Error getting channel info: {str(e)}")
        return None

def parse_duration(duration):
    """Parse ISO 8601 duration to readable format"""
    if not duration or duration == 'P0D':
        return "Live/Ongoing"
    
    pattern = r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?'
    match = re.match(pattern, duration)
    if not match:
        return "0:00"
    
    hours, minutes, seconds = match.groups()
    hours = int(hours) if hours else 0
    minutes = int(minutes) if minutes else 0
    seconds = int(seconds) if seconds else 0
    
    if hours > 0:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    else:
        return f"{minutes}:{seconds:02d}"

def format_number(num):
    """Format large numbers with K, M, B suffixes"""
    if pd.isna(num) or num == 0:
        return "0"
    if num >= 1_000_000_000:
        return f"{num/1_000_000_000:.1f}B"
    elif num >= 1_000_000:
        return f"{num/1_000_000:.1f}M"
    elif num >= 1_000:
        return f"{num/1_000:.1f}K"
    else:
        return str(int(num))

def get_uploaded_videos(youtube, channel_info, progress_callback=None):
    """Get all uploaded videos from a channel"""
    try:
        uploads_playlist_id = channel_info['uploads_playlist_id']
        all_videos = []
        next_page_token = None
        
        while True:
            # Get playlist items
            playlist_response = youtube.playlistItems().list(
                part='snippet',
                playlistId=uploads_playlist_id,
                maxResults=50,
                pageToken=next_page_token
            ).execute()
            
            # Extract video IDs
            video_ids = [item['snippet']['resourceId']['videoId'] for item in playlist_response['items']]
            
            # Get video details in batch
            videos_response = youtube.videos().list(
                part='snippet,statistics,contentDetails,liveStreamingDetails',
                id=','.join(video_ids)
            ).execute()
            
            # Process videos
            for playlist_item, video_detail in zip(playlist_response['items'], videos_response['items']):
                # Determine video type
                live_details = video_detail.get('liveStreamingDetails', {})
                video_type = "Video"
                
                if live_details:
                    if live_details.get('actualEndTime'):
                        video_type = "Live Stream (Ended)"
                    elif live_details.get('actualStartTime'):
                        video_type = "Live Stream (Active)"
                    else:
                        video_type = "Live Stream (Scheduled)"
                
                # Check if it's a Short (duration < 60 seconds)
                duration_iso = video_detail['contentDetails']['duration']
                if duration_iso and duration_iso != 'P0D':
                    duration_match = re.match(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?', duration_iso)
                    if duration_match:
                        hours, minutes, seconds = duration_match.groups()
                        total_seconds = (int(hours) if hours else 0) * 3600 + \
                                      (int(minutes) if minutes else 0) * 60 + \
                                      (int(seconds) if seconds else 0)
                        if total_seconds <= 60 and video_type == "Video":
                            video_type = "Short"
                
                # Get tags
                tags = video_detail['snippet'].get('tags', [])
                tags_str = ', '.join(tags) if tags else 'No tags'
                
                video_data = {
                    'Channel_Name': channel_info['title'],
                    'Type': video_type,
                    'Title': playlist_item['snippet']['title'],
                    'Published': datetime.fromisoformat(playlist_item['snippet']['publishedAt'].replace('Z', '+00:00')).strftime('%Y-%m-%d'),
                    'Duration': parse_duration(video_detail['contentDetails']['duration']),
                    'Views': int(video_detail['statistics'].get('viewCount', 0)),
                    'Views_Formatted': format_number(int(video_detail['statistics'].get('viewCount', 0))),
                    'Likes': int(video_detail['statistics'].get('likeCount', 0)),
                    'Likes_Formatted': format_number(int(video_detail['statistics'].get('likeCount', 0))),
                    'Comments': int(video_detail['statistics'].get('commentCount', 0)),
                    'Comments_Formatted': format_number(int(video_detail['statistics'].get('commentCount', 0))),
                    'Tags': tags_str,
                    'Content_ID': playlist_item['snippet']['resourceId']['videoId'],
                    'URL': f"https://youtu.be/{playlist_item['snippet']['resourceId']['videoId']}"
                }
                all_videos.append(video_data)
            
            if progress_callback:
                progress_callback(f"Fetched {len(all_videos)} videos...")
            
            next_page_token = playlist_response.get('nextPageToken')
            if not next_page_token:
                break
        
        return all_videos
        
    except Exception as e:
        st.error(f"Error fetching uploaded videos: {str(e)}")
        return []

def get_live_videos(youtube, channel_id, progress_callback=None):
    """Get live videos that might not be in uploads playlist"""
    try:
        all_live_videos = []
        next_page_token = None
        
        # Search for live videos
        while True:
            search_response = youtube.search().list(
                part='snippet',
                channelId=channel_id,
                type='video',
                eventType='completed',  # Past live streams
                maxResults=50,
                pageToken=next_page_token,
                order='date'
            ).execute()
            
            if not search_response['items']:
                break
                
            # Get video IDs
            video_ids = [item['id']['videoId'] for item in search_response['items']]
            
            # Get detailed video information
            videos_response = youtube.videos().list(
                part='snippet,statistics,contentDetails,liveStreamingDetails',
                id=','.join(video_ids)
            ).execute()
            
            for video_detail in videos_response['items']:
                live_details = video_detail.get('liveStreamingDetails', {})
                
                # Only include if it has live streaming details
                if live_details:
                    tags = video_detail['snippet'].get('tags', [])
                    tags_str = ', '.join(tags) if tags else 'No tags'
                    
                    video_data = {
                        'Channel_Name': video_detail['snippet']['channelTitle'],
                        'Type': 'Live Stream (Completed)',
                        'Title': video_detail['snippet']['title'],
                        'Published': datetime.fromisoformat(video_detail['snippet']['publishedAt'].replace('Z', '+00:00')).strftime('%Y-%m-%d'),
                        'Duration': parse_duration(video_detail['contentDetails']['duration']),
                        'Views': int(video_detail['statistics'].get('viewCount', 0)),
                        'Views_Formatted': format_number(int(video_detail['statistics'].get('viewCount', 0))),
                        'Likes': int(video_detail['statistics'].get('likeCount', 0)),
                        'Likes_Formatted': format_number(int(video_detail['statistics'].get('likeCount', 0))),
                        'Comments': int(video_detail['statistics'].get('commentCount', 0)),
                        'Comments_Formatted': format_number(int(video_detail['statistics'].get('commentCount', 0))),
                        'Tags': tags_str,
                        'Content_ID': video_detail['id'],
                        'URL': f"https://youtu.be/{video_detail['id']}"
                    }
                    all_live_videos.append(video_data)
            
            if progress_callback:
                progress_callback(f"Found {len(all_live_videos)} additional live videos...")
            
            next_page_token = search_response.get('nextPageToken')
            if not next_page_token:
                break
        
        return all_live_videos
        
    except Exception as e:
        st.error(f"Error fetching live videos: {str(e)}")
        return []

def get_playlists(youtube, channel_id, progress_callback=None):
    """Get all playlists from a channel"""
    try:
        all_playlists = []
        next_page_token = None
        
        while True:
            playlists_response = youtube.playlists().list(
                part='snippet,contentDetails,status',
                channelId=channel_id,
                maxResults=50,
                pageToken=next_page_token
            ).execute()
            
            for playlist in playlists_response['items']:
                # Skip auto-generated playlists
                if playlist['snippet']['title'] in ['Uploads', 'Liked videos', 'Favorites']:
                    continue
                
                playlist_data = {
                    'Channel_Name': playlist['snippet']['channelTitle'],
                    'Type': 'Playlist',
                    'Title': playlist['snippet']['title'],
                    'Published': datetime.fromisoformat(playlist['snippet']['publishedAt'].replace('Z', '+00:00')).strftime('%Y-%m-%d'),
                    'Duration': f"{playlist['contentDetails']['itemCount']} videos",
                    'Views': 0,  # Playlists don't have view counts
                    'Views_Formatted': 'N/A',
                    'Likes': 0,
                    'Likes_Formatted': 'N/A',
                    'Comments': 0,
                    'Comments_Formatted': 'N/A',
                    'Tags': playlist['snippet'].get('description', 'No description')[:100] + '...' if len(playlist['snippet'].get('description', '')) > 100 else playlist['snippet'].get('description', 'No description'),
                    'Content_ID': playlist['id'],
                    'URL': f"https://youtube.com/playlist?list={playlist['id']}"
                }
                all_playlists.append(playlist_data)
            
            if progress_callback:
                progress_callback(f"Found {len(all_playlists)} playlists...")
            
            next_page_token = playlists_response.get('nextPageToken')
            if not next_page_token:
                break
        
        return all_playlists
        
    except Exception as e:
        st.error(f"Error fetching playlists: {str(e)}")
        return []

def get_all_channel_content(youtube, channel_input):
    """Get all content from a channel - videos, live streams, and playlists"""
    try:
        # Determine channel ID
        channel_id = None
        
        if channel_input.startswith('UC') and len(channel_input) == 24:
            channel_id = channel_input
        elif 'youtube.com' in channel_input:
            extracted_id, pattern = extract_channel_id_from_url(channel_input)
            if extracted_id:
                if 'channel/' in pattern:
                    channel_id = extracted_id
                else:
                    channel_id = get_channel_id_from_username(youtube, extracted_id)
        else:
            channel_id = get_channel_id_from_username(youtube, channel_input)
        
        if not channel_id:
            st.error("Could not find channel. Please check your input.")
            return None, None
        
        # Get channel info
        channel_info = get_channel_info(youtube, channel_id)
        if not channel_info:
            st.error("Could not retrieve channel information.")
            return None, None
        
        progress_placeholder = st.empty()
        
        # Get all content types
        all_content = []
        
        # 1. Get uploaded videos
        progress_placeholder.text("Fetching uploaded videos...")
        uploaded_videos = get_uploaded_videos(youtube, channel_info, 
                                           lambda msg: progress_placeholder.text(f"Videos: {msg}"))
        all_content.extend(uploaded_videos)
        
        # 2. Get additional live videos (that might not be in uploads)
        progress_placeholder.text("Fetching additional live streams...")
        live_videos = get_live_videos(youtube, channel_id, 
                                    lambda msg: progress_placeholder.text(f"Live: {msg}"))
        
        # Remove duplicates (live videos that are already in uploads)
        existing_ids = {item['Content_ID'] for item in all_content}
        unique_live_videos = [video for video in live_videos if video['Content_ID'] not in existing_ids]
        all_content.extend(unique_live_videos)
        
        # 3. Get playlists
        progress_placeholder.text("Fetching playlists...")
        playlists = get_playlists(youtube, channel_id, 
                                lambda msg: progress_placeholder.text(f"Playlists: {msg}"))
        all_content.extend(playlists)
        
        progress_placeholder.empty()
        
        # Create DataFrame and sort by published date (newest first)
        df = pd.DataFrame(all_content)
        if not df.empty:
            df['Published_Sort'] = pd.to_datetime(df['Published'])
            df = df.sort_values('Published_Sort', ascending=False).drop('Published_Sort', axis=1)
        
        return df, channel_info
        
    except HttpError as e:
        st.error(f"YouTube API Error: {str(e)}")
        return None, None
    except Exception as e:
        st.error(f"Error fetching content: {str(e)}")
        return None, None

def create_excel_file(df, channel_info):
    """Create Excel file with content data"""
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        # Write content data
        df.to_excel(writer, sheet_name='All_Content', index=False)
        
        # Write channel info
        channel_df = pd.DataFrame([channel_info])
        channel_df.to_excel(writer, sheet_name='Channel_Info', index=False)
        
        # Create separate sheets for each content type
        if not df.empty:
            content_types = df['Type'].unique()
            for content_type in content_types:
                type_df = df[df['Type'] == content_type]
                sheet_name = content_type.replace(' ', '_').replace('(', '').replace(')', '')[:31]  # Excel sheet name limit
                type_df.to_excel(writer, sheet_name=sheet_name, index=False)
    
    output.seek(0)
    return output.getvalue()

def main():
    st.title("🎥 YouTube Channel Content Fetcher")
    st.markdown("*Fetch videos, live streams, shorts, and playlists*")
    
    # API Key input
    col1, col2 = st.columns([3, 1])
    with col1:
        api_key = st.text_input("YouTube API Key", type="password", placeholder="Enter your YouTube Data API v3 key")
    with col2:
        if st.button("ℹ️ API Help"):
            st.info("Get your API key from Google Cloud Console → YouTube Data API v3")
    
    if not api_key:
        st.warning("⚠️ Please enter your YouTube API key to continue.")
        return
    
    youtube = get_youtube_service(api_key)
    if not youtube:
        return
    
    # Channel input
    st.markdown("---")
    col1, col2 = st.columns([4, 1])
    
    with col1:
        channel_input = st.text_input(
            "Channel ID / Username / Handle / URL",
            placeholder="e.g., UCuAXFkgsw1L7xaCfnd5JJOw or @channelname"
        )
    
    with col2:
        st.markdown("<br>", unsafe_allow_html=True)  # Add spacing
        fetch_button = st.button("🔍 Fetch All", type="primary", use_container_width=True)
    
    # Fetch and display results
    if fetch_button and channel_input:
        with st.spinner("Fetching all channel content..."):
            df, channel_info = get_all_channel_content(youtube, channel_input.strip())
            if df is not None and channel_info:
                st.session_state.content_df = df
                st.session_state.channel_info = channel_info
                st.success(f"✅ Fetched {len(df)} items from '{channel_info['title']}'")
    
    # Display results if available
    if st.session_state.content_df is not None and st.session_state.channel_info:
        df = st.session_state.content_df
        channel_info = st.session_state.channel_info
        
        # Channel stats
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("📺 Channel", channel_info['title'])
        with col2:
            st.metric("📊 Total Items", len(df))
        with col3:
            subs = channel_info['subscriber_count']
            if subs != 'N/A':
                st.metric("👥 Subscribers", format_number(int(subs)))
            else:
                st.metric("👥 Subscribers", "Hidden")
        with col4:
            total_views = df[df['Type'] != 'Playlist']['Views'].sum()
            st.metric("👀 Total Views", format_number(total_views))
        
        # Content type breakdown
        if not df.empty:
            type_counts = df['Type'].value_counts()
            st.markdown("### Content Breakdown")
            cols = st.columns(len(type_counts))
            for i, (content_type, count) in enumerate(type_counts.items()):
                with cols[i]:
                    st.metric(content_type, count)
        
        # Download button
        excel_data = create_excel_file(df, channel_info)
        st.download_button(
            label="📊 Download Excel",
            data=excel_data,
            file_name=f"{channel_info['title']}_content_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )
        
        # Filter and search options
        st.markdown("---")
        col1, col2 = st.columns(2)
        with col1:
            content_type_filter = st.selectbox(
                "Filter by type",
                ['All'] + list(df['Type'].unique()),
                index=0
            )
        with col2:
            search_term = st.text_input("🔍 Search by title")
        
        # Filter dataframe
        display_df = df.copy()
        
        if content_type_filter != 'All':
            display_df = display_df[display_df['Type'] == content_type_filter]
        
        if search_term:
            mask = display_df['Title'].str.contains(search_term, case=False, na=False)
            display_df = display_df[mask]
        
        if len(display_df) != len(df):
            st.info(f"Showing {len(display_df)} of {len(df)} items")
        
        # Display options
        col1, col2, col3 = st.columns(3)
        with col1:
            show_raw_numbers = st.checkbox("Show raw numbers", help="Display exact view/like/comment counts")
        with col2:
            show_tags = st.checkbox("Show tags/description", help="Display tags or description")
        with col3:
            rows_to_show = st.selectbox("Rows to display", [10, 25, 50, 100, "All"], index=1)
        
        # Prepare display dataframe
        base_columns = ['Type', 'Title', 'Published', 'Duration']
        if show_raw_numbers:
            stat_columns = ['Views', 'Likes', 'Comments']
        else:
            stat_columns = ['Views_Formatted', 'Likes_Formatted', 'Comments_Formatted']
        
        end_columns = ['URL']
        if show_tags:
            end_columns = ['Tags', 'URL']
        
        # Select columns for display
        display_columns = base_columns + stat_columns + end_columns
        display_df = display_df[display_columns].copy()
        
        # Rename formatted columns for cleaner display
        if not show_raw_numbers:
            display_df = display_df.rename(columns={
                'Views_Formatted': 'Views',
                'Likes_Formatted': 'Likes',
                'Comments_Formatted': 'Comments'
            })
        
        # Limit rows if specified
        if rows_to_show != "All":
            display_df = display_df.head(rows_to_show)
        
        # Display the dataframe
        st.dataframe(
            display_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "URL": st.column_config.LinkColumn("URL", display_text="🔗 View"),
                "Type": st.column_config.TextColumn("Type", width="small"),
                "Title": st.column_config.TextColumn("Title", width="large"),
                "Published": st.column_config.TextColumn("Published", width="small"),
                "Duration": st.column_config.TextColumn("Duration", width="small"),
                "Views": st.column_config.TextColumn("Views", width="small"),
                "Likes": st.column_config.TextColumn("Likes", width="small"),
                "Comments": st.column_config.TextColumn("Comments", width="small"),
                "Tags": st.column_config.TextColumn("Tags/Description", width="medium")
            }
        )

if __name__ == '__main__':
    main()