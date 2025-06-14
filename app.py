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
if 'videos_data' not in st.session_state:
    st.session_state.videos_data = None
if 'channel_info' not in st.session_state:
    st.session_state.channel_info = None

def get_youtube_service(api_key):
    """Initialize YouTube API service"""
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
        # Try different methods to get channel ID
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
        
        # If direct methods fail, try searching
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
    """Get channel information"""
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
            'description': channel['snippet']['description'][:200] + '...' if len(channel['snippet']['description']) > 200 else channel['snippet']['description'],
            'subscriber_count': channel['statistics'].get('subscriberCount', 'N/A'),
            'video_count': channel['statistics'].get('videoCount', 'N/A'),
            'view_count': channel['statistics'].get('viewCount', 'N/A'),
            'uploads_playlist_id': channel['contentDetails']['relatedPlaylists']['uploads']
        }
    except Exception as e:
        st.error(f"Error getting channel info: {str(e)}")
        return None

def get_video_details(youtube, video_ids):
    """Get detailed information for videos"""
    try:
        # Split video IDs into chunks of 50 (API limit)
        video_details = []
        for i in range(0, len(video_ids), 50):
            chunk = video_ids[i:i+50]
            response = youtube.videos().list(
                part='snippet,statistics,contentDetails',
                id=','.join(chunk)
            ).execute()
            video_details.extend(response['items'])
        
        return video_details
    except Exception as e:
        st.error(f"Error getting video details: {str(e)}")
        return []

def parse_duration(duration):
    """Parse ISO 8601 duration to readable format"""
    import re
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

def get_all_videos(youtube, channel_input):
    """Get all videos from a channel"""
    try:
        # Determine if input is channel ID, username, or URL
        channel_id = None
        
        if channel_input.startswith('UC') and len(channel_input) == 24:
            # Looks like a channel ID
            channel_id = channel_input
        elif 'youtube.com' in channel_input:
            # It's a URL
            extracted_id, pattern = extract_channel_id_from_url(channel_input)
            if extracted_id:
                if 'channel/' in pattern:
                    channel_id = extracted_id
                else:
                    channel_id = get_channel_id_from_username(youtube, extracted_id)
        else:
            # Treat as username/handle
            channel_id = get_channel_id_from_username(youtube, channel_input)
        
        if not channel_id:
            st.error("Could not find channel. Please check your input.")
            return None, None
        
        # Get channel info
        channel_info = get_channel_info(youtube, channel_id)
        if not channel_info:
            st.error("Could not retrieve channel information.")
            return None, None
        
        # Get uploads playlist ID
        uploads_playlist_id = channel_info['uploads_playlist_id']
        
        # Get all videos from uploads playlist
        videos = []
        next_page_token = None
        
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        while True:
            response = youtube.playlistItems().list(
                part='snippet',
                playlistId=uploads_playlist_id,
                maxResults=50,
                pageToken=next_page_token
            ).execute()
            
            video_ids = []
            for item in response['items']:
                video_ids.append(item['snippet']['resourceId']['videoId'])
            
            # Get detailed video information
            video_details = get_video_details(youtube, video_ids)
            
            for item, details in zip(response['items'], video_details):
                video_data = {
                    'title': item['snippet']['title'],
                    'video_id': item['snippet']['resourceId']['videoId'],
                    'published_at': item['snippet']['publishedAt'],
                    'description': item['snippet']['description'][:500] + '...' if len(item['snippet']['description']) > 500 else item['snippet']['description'],
                    'thumbnail_url': item['snippet']['thumbnails'].get('medium', {}).get('url', ''),
                    'duration': parse_duration(details['contentDetails']['duration']),
                    'view_count': int(details['statistics'].get('viewCount', 0)),
                    'like_count': int(details['statistics'].get('likeCount', 0)),
                    'comment_count': int(details['statistics'].get('commentCount', 0)),
                    'video_url': f"https://youtu.be/{item['snippet']['resourceId']['videoId']}"
                }
                videos.append(video_data)
            
            videos_fetched = len(videos)
            status_text.text(f"Fetched {videos_fetched} videos...")
            progress_bar.progress(min(videos_fetched / int(channel_info['video_count']) if channel_info['video_count'] != 'N/A' else videos_fetched / 100, 1.0))
            
            next_page_token = response.get('nextPageToken')
            if not next_page_token:
                break
        
        progress_bar.empty()
        status_text.empty()
        
        # Sort by published date (newest to oldest)
        videos.sort(key=lambda x: x['published_at'], reverse=True)
        
        return videos, channel_info
        
    except HttpError as e:
        st.error(f"YouTube API Error: {str(e)}")
        return None, None
    except Exception as e:
        st.error(f"Error fetching videos: {str(e)}")
        return None, None

def format_number(num):
    """Format large numbers with K, M, B suffixes"""
    if num >= 1_000_000_000:
        return f"{num/1_000_000_000:.1f}B"
    elif num >= 1_000_000:
        return f"{num/1_000_000:.1f}M"
    elif num >= 1_000:
        return f"{num/1_000:.1f}K"
    else:
        return str(num)

def create_excel_file(videos_data, channel_info):
    """Create Excel file with video data"""
    df = pd.DataFrame(videos_data)
    
    # Format the dataframe
    df['published_at'] = pd.to_datetime(df['published_at']).dt.strftime('%Y-%m-%d %H:%M:%S')
    df['view_count_formatted'] = df['view_count'].apply(format_number)
    df['like_count_formatted'] = df['like_count'].apply(format_number)
    df['comment_count_formatted'] = df['comment_count'].apply(format_number)
    
    # Reorder columns
    columns_order = [
        'title', 'published_at', 'duration', 'view_count', 'view_count_formatted',
        'like_count', 'like_count_formatted', 'comment_count', 'comment_count_formatted',
        'video_url', 'video_id', 'description', 'thumbnail_url'
    ]
    df = df[columns_order]
    
    # Create Excel file in memory
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        # Write videos data
        df.to_excel(writer, sheet_name='Videos', index=False)
        
        # Write channel info
        channel_df = pd.DataFrame([channel_info])
        channel_df.to_excel(writer, sheet_name='Channel Info', index=False)
        
        # Auto-adjust column widths
        for sheet_name in writer.sheets:
            worksheet = writer.sheets[sheet_name]
            for col in worksheet.columns:
                max_length = 0
                column = col[0].column_letter
                for cell in col:
                    try:
                        if len(str(cell.value)) > max_length:
                            max_length = len(str(cell.value))
                    except:
                        pass
                adjusted_width = min(max_length + 2, 50)
                worksheet.column_dimensions[column].width = adjusted_width
    
    output.seek(0)
    return output.getvalue()

# Streamlit App
def main():
    st.title("🎥 YouTube Channel Video Fetcher")
    st.markdown("Fetch all videos from a YouTube channel with detailed metadata")
    
    # Sidebar for API key
    with st.sidebar:
        st.header("🔑 Configuration")
        api_key = st.text_input(
            "YouTube API Key",
            type="password",
            help="Enter your YouTube Data API v3 key. Get one from Google Cloud Console."
        )
        
        if not api_key:
            st.warning("Please enter your YouTube API key to continue.")
            st.markdown("### How to get an API key:")
            st.markdown("""
            1. Go to [Google Cloud Console](https://console.cloud.google.com/)
            2. Create a new project or select existing one
            3. Enable YouTube Data API v3
            4. Create credentials (API key)
            5. Copy and paste the API key here
            """)
    
    if api_key:
        youtube = get_youtube_service(api_key)
        
        if youtube:
            # Input section
            st.header("📝 Channel Input")
            col1, col2 = st.columns([3, 1])
            
            with col1:
                channel_input = st.text_input(
                    "Enter Channel ID, Username, Handle, or URL",
                    placeholder="e.g., UCuAXFkgsw1L7xaCfnd5JJOw, @channelname, or https://youtube.com/c/channelname",
                    help="You can enter: Channel ID (starts with UC), Username, Handle (@username), or any YouTube channel URL"
                )
            
            with col2:
                fetch_button = st.button("🔍 Fetch Videos", type="primary")
            
            # Fetch videos
            if fetch_button and channel_input:
                with st.spinner("Fetching videos..."):
                    videos, channel_info = get_all_videos(youtube, channel_input.strip())
                    if videos and channel_info:
                        st.session_state.videos_data = videos
                        st.session_state.channel_info = channel_info
                        st.success(f"Successfully fetched {len(videos)} videos!")
            
            # Display results
            if st.session_state.videos_data and st.session_state.channel_info:
                videos = st.session_state.videos_data
                channel_info = st.session_state.channel_info
                
                # Channel Information
                st.header("📊 Channel Information")
                col1, col2, col3, col4 = st.columns(4)
                
                with col1:
                    st.metric("Channel", channel_info['title'])
                with col2:
                    st.metric("Total Videos", len(videos))
                with col3:
                    if channel_info['subscriber_count'] != 'N/A':
                        st.metric("Subscribers", format_number(int(channel_info['subscriber_count'])))
                    else:
                        st.metric("Subscribers", "Hidden")
                with col4:
                    if channel_info['view_count'] != 'N/A':
                        st.metric("Total Views", format_number(int(channel_info['view_count'])))
                    else:
                        st.metric("Total Views", "N/A")
                
                # Download button
                st.header("📥 Download Data")
                excel_data = create_excel_file(videos, channel_info)
                st.download_button(
                    label="📊 Download as Excel",
                    data=excel_data,
                    file_name=f"{channel_info['title']}_videos_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
                
                # Videos Display
                st.header("🎬 Videos")
                
                # Search and filter
                search_term = st.text_input("🔍 Search videos", placeholder="Search by title...")
                
                # Filter videos based on search
                filtered_videos = videos
                if search_term:
                    filtered_videos = [v for v in videos if search_term.lower() in v['title'].lower()]
                
                st.write(f"Showing {len(filtered_videos)} of {len(videos)} videos")
                
                # Display videos
                for i, video in enumerate(filtered_videos):
                    with st.expander(f"🎥 {video['title']}", expanded=i < 3):
                        col1, col2 = st.columns([1, 2])
                        
                        with col1:
                            if video['thumbnail_url']:
                                st.image(video['thumbnail_url'], width=300)
                        
                        with col2:
                            st.write(f"**Published:** {datetime.fromisoformat(video['published_at'].replace('Z', '+00:00')).strftime('%Y-%m-%d %H:%M:%S')}")
                            st.write(f"**Duration:** {video['duration']}")
                            st.write(f"**Views:** {format_number(video['view_count'])}")
                            st.write(f"**Likes:** {format_number(video['like_count'])}")
                            st.write(f"**Comments:** {format_number(video['comment_count'])}")
                            st.write(f"**URL:** [Watch Video]({video['video_url']})")
                            
                            if video['description']:
                                st.write("**Description:**")
                                st.write(video['description'])

if __name__ == '__main__':
    main()