import streamlit as st
import pandas as pd
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import os
from datetime import datetime
import re
from io import BytesIO
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# Set page config for mobile-optimized experience
st.set_page_config(
    page_title="YT Content Fetcher",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Custom CSS for ultra-modern mobile design
st.markdown("""
<style>
/* --------------------------------------------------
   Simple, readable palette (light-mode friendly).
   Works fine in Streamlit dark-mode too.
---------------------------------------------------*/
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap');
:root{
  --primary : #3B82F6;          /* blue-500  */
  --neutral : #111827;          /* gray-900  */
  --neutral-light: #6B7280;     /* gray-500  */
  --card-bg: #F9FAFB;           /* gray-50   */
}

*{font-family:'Inter',sans-serif !important;}
#MainMenu, footer, header, .stDeployButton{display:none}

/* Page background (falls back to Streamlit default in dark mode) */
.stApp{background:#ffffff;}

/* ------------- Inputs & selects --------------- */
.stTextInput  input,
.stNumberInput input,
.stSelectbox  > div > div{
  background:#fff !important;
  color:var(--neutral) !important;
  border:1px solid #D1D5DB !important;   /* gray-300 */
  border-radius:8px !important;
  padding:.6rem .8rem !important;
}
.stTextInput  input:focus,
.stNumberInput input:focus,
.stSelectbox  > div > div:focus-within{
  border-color:var(--primary) !important;
  box-shadow:0 0 0 2px rgba(59,130,246, .35) !important; /* blue-500 @ 35% */
}
.stTextInput input::placeholder{color:#9CA3AF !important;}  /* gray-400 */

/* ---------------- Buttons --------------------- */
.stButton > button{
  background:var(--primary) !important;
  color:#fff !important;
  border:none !important;
  border-radius:8px !important;
  padding:.6rem 1.6rem !important;
  font-weight:600 !important;
  transition:filter .15s;
}
.stButton > button:hover{filter:brightness(0.92);}

/* --------------- Metrics ---------------------- */
.metric-row{gap:1rem}                  /* utility class below */
.metric-card{
  background:var(--card-bg);
  border:1px solid #E5E7EB;            /* gray-200 */
  border-radius:10px;
  padding:1rem 1.2rem;
  text-align:center;
}
.metric-value{font-size:1.4rem;font-weight:600;color:var(--primary);}
.metric-label{font-size:.85rem;color:var(--neutral-light);}

/* --------------- Dataframe tweaks ------------- */
.stDataFrame{border:1px solid #E5E7EB;border-radius:8px;}
.stDataFrame table thead tr th{background:#F3F4F6;color:var(--neutral);}

/* --------------- Progress & spinner ----------- */
.stProgress > div > div > div{background:var(--primary) !important;}
.stSpinner > div{border-top-color:var(--primary) !important;}
</style>
""", unsafe_allow_html=True)



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
        st.error(f"🚫 Failed to initialize YouTube API: {str(e)}")
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
        st.error(f"🔍 Error finding channel: {str(e)}")
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
        st.error(f"📊 Error getting channel info: {str(e)}")
        return None

def parse_duration(duration):
    """Parse ISO 8601 duration to readable format"""
    if not duration or duration == 'P0D':
        return "🔴 Live"
    
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
            playlist_response = youtube.playlistItems().list(
                part='snippet',
                playlistId=uploads_playlist_id,
                maxResults=50,
                pageToken=next_page_token
            ).execute()
            
            video_ids = [item['snippet']['resourceId']['videoId'] for item in playlist_response['items']]
            
            videos_response = youtube.videos().list(
                part='snippet,statistics,contentDetails,liveStreamingDetails',
                id=','.join(video_ids)
            ).execute()
            
            for playlist_item, video_detail in zip(playlist_response['items'], videos_response['items']):
                live_details = video_detail.get('liveStreamingDetails', {})
                video_type = "📹 Video"
                
                if live_details:
                    if live_details.get('actualEndTime'):
                        video_type = "🔴 Live (Ended)"
                    elif live_details.get('actualStartTime'):
                        video_type = "🔴 Live (Active)"
                    else:
                        video_type = "🔴 Live (Scheduled)"
                
                duration_iso = video_detail['contentDetails']['duration']
                if duration_iso and duration_iso != 'P0D':
                    duration_match = re.match(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?', duration_iso)
                    if duration_match:
                        hours, minutes, seconds = duration_match.groups()
                        total_seconds = (int(hours) if hours else 0) * 3600 + \
                                      (int(minutes) if minutes else 0) * 60 + \
                                      (int(seconds) if seconds else 0)
                        if total_seconds <= 60 and video_type == "📹 Video":
                            video_type = "⚡ Short"
                
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
                progress_callback(f"🎬 Fetched {len(all_videos)} videos")
            
            next_page_token = playlist_response.get('nextPageToken')
            if not next_page_token:
                break
        
        return all_videos
        
    except Exception as e:
        st.error(f"🎬 Error fetching videos: {str(e)}")
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
                if playlist['snippet']['title'] in ['Uploads', 'Liked videos', 'Favorites']:
                    continue
                
                playlist_data = {
                    'Channel_Name': playlist['snippet']['channelTitle'],
                    'Type': '📋 Playlist',
                    'Title': playlist['snippet']['title'],
                    'Published': datetime.fromisoformat(playlist['snippet']['publishedAt'].replace('Z', '+00:00')).strftime('%Y-%m-%d'),
                    'Duration': f"{playlist['contentDetails']['itemCount']} videos",
                    'Views': 0,
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
                progress_callback(f"📋 Found {len(all_playlists)} playlists")
            
            next_page_token = playlists_response.get('nextPageToken')
            if not next_page_token:
                break
        
        return all_playlists
        
    except Exception as e:
        st.error(f"📋 Error fetching playlists: {str(e)}")
        return []

def get_all_channel_content(youtube, channel_input):
    """Get all content from a channel"""
    try:
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
            st.error("🚫 Channel not found! Please check your input.")
            return None, None
        
        channel_info = get_channel_info(youtube, channel_id)
        if not channel_info:
            st.error("📊 Could not retrieve channel information.")
            return None, None
        
        progress_placeholder = st.empty()
        all_content = []
        
        progress_placeholder.info("🎬 Fetching videos...")
        uploaded_videos = get_uploaded_videos(youtube, channel_info, 
                                           lambda msg: progress_placeholder.info(msg))
        all_content.extend(uploaded_videos)
        
        progress_placeholder.info("📋 Fetching playlists...")
        playlists = get_playlists(youtube, channel_id, 
                                lambda msg: progress_placeholder.info(msg))
        all_content.extend(playlists)
        
        progress_placeholder.empty()
        
        df = pd.DataFrame(all_content)
        if not df.empty:
            df['Published_Sort'] = pd.to_datetime(df['Published'])
            df = df.sort_values('Published_Sort', ascending=False).drop('Published_Sort', axis=1)
        
        return df, channel_info
        
    except HttpError as e:
        st.error(f"🚫 YouTube API Error: {str(e)}")
        return None, None
    except Exception as e:
        st.error(f"💥 Error: {str(e)}")
        return None, None

def create_excel_file(df, channel_info):
    """Create Excel file with content data"""
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name='All_Content', index=False)
        
        channel_df = pd.DataFrame([channel_info])
        channel_df.to_excel(writer, sheet_name='Channel_Info', index=False)
        
        if not df.empty:
            content_types = df['Type'].unique()
            for content_type in content_types:
                type_df = df[df['Type'] == content_type]
                sheet_name = content_type.replace(' ', '_').replace('(', '').replace(')', '').replace('📹', '').replace('⚡', '').replace('🔴', '').replace('📋', '').strip()[:31]
                type_df.to_excel(writer, sheet_name=sheet_name, index=False)
    
    output.seek(0)
    return output.getvalue()

def create_analytics_charts(df):
    """Create beautiful analytics charts"""
    if df.empty:
        return None, None
    
    # Content type distribution
    type_counts = df['Type'].value_counts()
    
    fig_pie = px.pie(
        values=type_counts.values,
        names=type_counts.index,
        title="📊 Content Distribution",
        color_discrete_sequence=px.colors.qualitative.Set3
    )
    fig_pie.update_layout(
        plot_bgcolor='rgba(0,0,0,0)',
        paper_bgcolor='rgba(0,0,0,0)',
        font_color='white',
        title_font_size=20
    )
    
    # Views over time (for videos only)
    video_df = df[df['Type'].str.contains('Video|Short')].copy()
    if not video_df.empty:
        video_df['Published_Date'] = pd.to_datetime(video_df['Published'])
        video_df = video_df.sort_values('Published_Date')
        
        fig_timeline = px.scatter(
            video_df,
            x='Published_Date',
            y='Views',
            size='Views',
            color='Type',
            title="📈 Views Timeline",
            hover_data=['Title', 'Views_Formatted'],
            color_discrete_sequence=px.colors.qualitative.Vivid
        )
        fig_timeline.update_layout(
            plot_bgcolor='rgba(0,0,0,0)',
            paper_bgcolor='rgba(0,0,0,0)',
            font_color='white',
            title_font_size=20
        )
        fig_timeline.update_traces(marker=dict(line=dict(width=2, color='white')))
    else:
        fig_timeline = None
    
    return fig_pie, fig_timeline

def main():
    # Hero section
    st.markdown("""
    <div class="hero">
        <h1>🚀 YT Fetcher</h1>
        <p>Extract YouTube content like a pro</p>
    </div>
    """, unsafe_allow_html=True)
    
    # API Key section
    st.markdown('<div class="glass-container">', unsafe_allow_html=True)
    
    col1, col2 = st.columns([4, 1])
    with col1:
        api_key = st.text_input("🔑 YouTube API Key", type="password", placeholder="Enter your API key")
    with col2:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("ℹ️"):
            st.info("🔗 Get your API key from Google Cloud Console → YouTube Data API v3")
    
    st.markdown('</div>', unsafe_allow_html=True)
    
    if not api_key:
        st.warning("⚠️ Please enter your YouTube API key to continue")
        return
    
    youtube = get_youtube_service(api_key)
    if not youtube:
        return
    
    # Channel input section
    st.markdown('<div class="glass-container">', unsafe_allow_html=True)
    
    col1, col2 = st.columns([3, 1])
    with col1:
        channel_input = st.text_input(
            "🎯 Channel Input",
            placeholder="@channelname or channel URL"
        )
    with col2:
        st.markdown("<br>", unsafe_allow_html=True)
        fetch_button = st.button("🚀 FETCH", type="primary")
    
    st.markdown('</div>', unsafe_allow_html=True)
    
    # Fetch results
    if fetch_button and channel_input:
        with st.spinner("🔄 Fetching content..."):
            df, channel_info = get_all_channel_content(youtube, channel_input.strip())
            if df is not None and channel_info:
                st.session_state.content_df = df
                st.session_state.channel_info = channel_info
                st.success(f"✅ Found {len(df)} items from **{channel_info['title']}**")
    
    # Display results
    if st.session_state.content_df is not None and st.session_state.channel_info:
        df = st.session_state.content_df
        channel_info = st.session_state.channel_info
        
        # Channel stats
        st.markdown('<div class="glass-container">', unsafe_allow_html=True)
        
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.markdown(f"""
            <div class="metric-card">
                <div class="metric-value">📺</div>
                <div class="metric-label">{channel_info['title'][:15]}...</div>
            </div>
            """, unsafe_allow_html=True)
        
        with col2:
            st.markdown(f"""
            <div class="metric-card">
                <div class="metric-value">{len(df)}</div>
                <div class="metric-label">Total Items</div>
            </div>
            """, unsafe_allow_html=True)
        
        with col3:
            subs = channel_info['subscriber_count']
            subs_formatted = format_number(int(subs)) if subs != 'N/A' else 'Hidden'
            st.markdown(f"""
            <div class="metric-card">
                <div class="metric-value">{subs_formatted}</div>
                <div class="metric-label">Subscribers</div>
            </div>
            """, unsafe_allow_html=True)
        
        with col4:
            total_views = df[df['Type'] != '📋 Playlist']['Views'].sum()
            st.markdown(f"""
            <div class="metric-card">
                <div class="metric-value">{format_number(total_views)}</div>
                <div class="metric-label">Total Views</div>
            </div>
            """, unsafe_allow_html=True)
        
        st.markdown('</div>', unsafe_allow_html=True)
        
        # Content breakdown
        if not df.empty:
            st.markdown('<div class="glass-container">', unsafe_allow_html=True)
            st.markdown("### 📊 Content Breakdown")
            
            type_counts = df['Type'].value_counts()
            cols = st.columns(len(type_counts))
            
            for i, (content_type, count) in enumerate(type_counts.items()):
                with cols[i]:
                    badge_class = "badge-video"
                    if "Short" in content_type:
                        badge_class = "badge-short"
                    elif "Live" in content_type:
                        badge_class = "badge-live"
                    elif "Playlist" in content_type:
                        badge_class = "badge-playlist"
                    
                    st.markdown(f"""
                    <div class="content-badge {badge_class}">
                        {content_type}: {count}
                    </div>
                    """, unsafe_allow_html=True)
            
            st.markdown('</div>', unsafe_allow_html=True)
        
        # Analytics charts
        st.markdown('<div class="glass-container">', unsafe_allow_html=True)
        st.markdown("### 📈 Analytics")
        
        fig_pie, fig_timeline = create_analytics_charts(df)
        
        if fig_pie:
            col1, col2 = st.columns(2)
            with col1:
                st.markdown('<div class="chart-container">', unsafe_allow_html=True)
                st.plotly_chart(fig_pie, use_container_width=True)
                st.markdown('</div>', unsafe_allow_html=True)
            
            if fig_timeline:
                with col2:
                    st.markdown('<div class="chart-container">', unsafe_allow_html=True)
                    st.plotly_chart(fig_timeline, use_container_width=True)
                    st.markdown('</div>', unsafe_allow_html=True)
        
        st.markdown('</div>', unsafe_allow_html=True)
        
        # Download section
        st.markdown('<div class="glass-container">', unsafe_allow_html=True)
        
        excel_data = create_excel_file(df, channel_info)
        st.download_button(
            label="📊 Download Excel Report",
            data=excel_data,
            file_name=f"{channel_info['title']}_content_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
            key="download_btn"
        )
        
        st.markdown('</div>', unsafe_allow_html=True)
        
        # Filters and search
        st.markdown('<div class="glass-container">', unsafe_allow_html=True)
        st.markdown("### 🔍 Filter & Search")
        
        col1, col2 = st.columns(2)
        with col1:
            content_type_filter = st.selectbox(
                "Filter by type",
                ['All'] + list(df['Type'].unique()),
                index=0
            )
        with col2:
            search_term = st.text_input("🔍 Search titles", placeholder="Search...")
        
        # Display options
        col1, col2, col3 = st.columns(3)
        with col1:
            show_raw_numbers = st.checkbox("Raw numbers", help="Show exact counts")
        with col2:
            show_tags = st.checkbox("Show tags", help="Display tags/description")
        with col3:
            rows_to_show = st.selectbox("Rows", [10, 25, 50, 100, "All"], index=1)
        
        st.markdown('</div>', unsafe_allow_html=True)
        
        # Filter dataframe
        display_df = df.copy()
        
        if content_type_filter != 'All':
            display_df = display_df[display_df['Type'] == content_type_filter]
        
        if search_term:
            mask = display_df['Title'].str.contains(search_term, case=False, na=False)
            display_df = display_df[mask]
        
        if len(display_df) != len(df):
            st.info(f"📊 Showing {len(display_df)} of {len(df)} items")
        
        # Prepare display dataframe
        base_columns = ['Type', 'Title', 'Published', 'Duration']
        if show_raw_numbers:
            stat_columns = ['Views', 'Likes', 'Comments']
        else:
            stat_columns = ['Views_Formatted', 'Likes_Formatted', 'Comments_Formatted']
        
        end_columns = ['URL']
        if show_tags:
            end_columns = ['Tags', 'URL']
        
        display_columns = base_columns + stat_columns + end_columns
        display_df = display_df[display_columns].copy()
        
        if not show_raw_numbers:
            display_df = display_df.rename(columns={
                'Views_Formatted': 'Views',
                'Likes_Formatted': 'Likes',
                'Comments_Formatted': 'Comments'
            })
        
        if rows_to_show != "All":
            display_df = display_df.head(rows_to_show)
        
        # Display table
        st.markdown('<div class="glass-container">', unsafe_allow_html=True)
        st.markdown("### 📋 Content Table")
        
        st.dataframe(
            display_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "URL": st.column_config.LinkColumn("🔗", display_text="View"),
                "Type": st.column_config.TextColumn("Type", width="small"),
                "Title": st.column_config.TextColumn("Title", width="large"),
                "Published": st.column_config.TextColumn("Date", width="small"),
                "Duration": st.column_config.TextColumn("Duration", width="small"),
                "Views": st.column_config.NumberColumn("👀 Views", width="small"),
                "Likes": st.column_config.NumberColumn("👍 Likes", width="small"),
                "Comments": st.column_config.NumberColumn("💬 Comments", width="small"),
                "Tags": st.column_config.TextColumn("Tags", width="medium")
            },
            height=600
        )
        
        st.markdown('</div>', unsafe_allow_html=True)
        
        # Footer
        st.markdown("""
        <div style="text-align: center; padding: 2rem; color: rgba(255,255,255,0.6);">
            <p>🚀 Built with Streamlit • Made for mobile-first experience</p>
        </div>
        """, unsafe_allow_html=True)

if __name__ == '__main__':
    main()