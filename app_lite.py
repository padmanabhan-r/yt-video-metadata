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
    page_title="YouTube Channel Video Fetcher",
    page_icon="🎥",
    layout="wide"
)

# Initialize session state
if 'videos_df' not in st.session_state:
    st.session_state.videos_df = None
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

def get_all_videos_fast(youtube, channel_input):
    """Get all videos from a channel - optimized for speed"""
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
        
        uploads_playlist_id = channel_info['uploads_playlist_id']
        
        # Get all videos efficiently
        all_videos = []
        next_page_token = None
        
        progress_placeholder = st.empty()
        
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
                part='snippet,statistics,contentDetails',
                id=','.join(video_ids)
            ).execute()
            
            # Process videos
            for playlist_item, video_detail in zip(playlist_response['items'], videos_response['items']):
                video_data = {
                    'Title': playlist_item['snippet']['title'],
                    'Published': datetime.fromisoformat(playlist_item['snippet']['publishedAt'].replace('Z', '+00:00')).strftime('%Y-%m-%d'),
                    'Duration': parse_duration(video_detail['contentDetails']['duration']),
                    'Views': int(video_detail['statistics'].get('viewCount', 0)),
                    'Views_Formatted': format_number(int(video_detail['statistics'].get('viewCount', 0))),
                    'Likes': int(video_detail['statistics'].get('likeCount', 0)),
                    'Likes_Formatted': format_number(int(video_detail['statistics'].get('likeCount', 0))),
                    'Comments': int(video_detail['statistics'].get('commentCount', 0)),
                    'Comments_Formatted': format_number(int(video_detail['statistics'].get('commentCount', 0))),
                    'Video_ID': playlist_item['snippet']['resourceId']['videoId'],
                    'URL': f"https://youtu.be/{playlist_item['snippet']['resourceId']['videoId']}"
                }
                all_videos.append(video_data)
            
            progress_placeholder.text(f"Fetched {len(all_videos)} videos...")
            
            next_page_token = playlist_response.get('nextPageToken')
            if not next_page_token:
                break
        
        progress_placeholder.empty()
        
        # Create DataFrame and sort by published date (newest first)
        df = pd.DataFrame(all_videos)
        df['Published_Sort'] = pd.to_datetime(df['Published'])
        df = df.sort_values('Published_Sort', ascending=False).drop('Published_Sort', axis=1)
        
        return df, channel_info
        
    except HttpError as e:
        st.error(f"YouTube API Error: {str(e)}")
        return None, None
    except Exception as e:
        st.error(f"Error fetching videos: {str(e)}")
        return None, None

def create_excel_file(df, channel_info):
    """Create Excel file with video data"""
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        # Write videos data
        df.to_excel(writer, sheet_name='Videos', index=False)
        
        # Write channel info
        channel_df = pd.DataFrame([channel_info])
        channel_df.to_excel(writer, sheet_name='Channel_Info', index=False)
    
    output.seek(0)
    return output.getvalue()

def main():
    st.title("🎥 YouTube Channel Video Fetcher")
    st.markdown("*Fast and efficient video data extraction*")
    
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
        fetch_button = st.button("🔍 Fetch", type="primary", use_container_width=True)
    
    # Fetch and display results
    if fetch_button and channel_input:
        with st.spinner("Fetching videos..."):
            df, channel_info = get_all_videos_fast(youtube, channel_input.strip())
            if df is not None and channel_info:
                st.session_state.videos_df = df
                st.session_state.channel_info = channel_info
                st.success(f"✅ Fetched {len(df)} videos from '{channel_info['title']}'")
    
    # Display results if available
    if st.session_state.videos_df is not None and st.session_state.channel_info:
        df = st.session_state.videos_df
        channel_info = st.session_state.channel_info
        
        # Channel stats
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("📺 Channel", channel_info['title'])
        with col2:
            st.metric("🎬 Videos", len(df))
        with col3:
            subs = channel_info['subscriber_count']
            if subs != 'N/A':
                st.metric("👥 Subscribers", format_number(int(subs)))
            else:
                st.metric("👥 Subscribers", "Hidden")
        with col4:
            total_views = df['Views'].sum()
            st.metric("👀 Total Views", format_number(total_views))
        
        # Download button
        excel_data = create_excel_file(df, channel_info)
        st.download_button(
            label="📊 Download Excel",
            data=excel_data,
            file_name=f"{channel_info['title']}_videos_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )
        
        # Search functionality
        search_term = st.text_input("🔍 Search videos by title")
        
        # Filter dataframe
        display_df = df.copy()
        if search_term:
            mask = display_df['Title'].str.contains(search_term, case=False, na=False)
            display_df = display_df[mask]
            st.info(f"Showing {len(display_df)} of {len(df)} videos")
        
        # Display configuration
        col1, col2 = st.columns(2)
        with col1:
            show_raw_numbers = st.checkbox("Show raw numbers", help="Display exact view/like/comment counts")
        with col2:
            rows_to_show = st.selectbox("Rows to display", [10, 25, 50, 100, "All"], index=1)
        
        # Prepare display dataframe
        if show_raw_numbers:
            display_df = display_df[['Title', 'Published', 'Duration', 'Views', 'Likes', 'Comments', 'URL']].copy()
        else:
            # Create a copy with formatted columns renamed for display
            display_df = display_df[['Title', 'Published', 'Duration', 'Views_Formatted', 'Likes_Formatted', 'Comments_Formatted', 'URL']].copy()
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
                "URL": st.column_config.LinkColumn("URL", display_text="🔗 Watch"),
                "Title": st.column_config.TextColumn("Title", width="large"),
                "Published": st.column_config.TextColumn("Published", width="small"),
                "Duration": st.column_config.TextColumn("Duration", width="small"),
                "Views": st.column_config.TextColumn("Views", width="small"),
                "Likes": st.column_config.TextColumn("Likes", width="small"),
                "Comments": st.column_config.TextColumn("Comments", width="small")
            }
        )

if __name__ == '__main__':
    main()