import streamlit as st
import os
import requests
import json
import time
from dotenv import load_dotenv
from camel.agents import ChatAgent
from camel.models import ModelFactory
from camel.types import ModelPlatformType, ModelType
from camel.configs import GroqConfig
from camel.toolkits import LinkedInToolkit
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

load_dotenv()

def get_session_with_retries():
    session = requests.Session()
    retry_strategy = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["HEAD", "GET", "PUT", "DELETE", "OPTIONS", "TRACE", "POST"]
    )
    adapter = HTTPAdapter(max_retries=retry_strategy, pool_connections=100, pool_maxsize=100)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session

linkedin_session = get_session_with_retries()

def get_file_size_mb(uploaded_file):
    if uploaded_file is None:
        return 0
    current_pos = uploaded_file.tell()
    uploaded_file.seek(0, 2)
    size = uploaded_file.tell()
    uploaded_file.seek(current_pos)
    return size / (1024 * 1024)

def check_linkedin_connection(access_token):
    if not access_token:
        return False
    try:
        headers = {'Authorization': f'Bearer {access_token}'}
        response = linkedin_session.get(
            'https://api.linkedin.com/v2/userinfo',
            headers=headers,
            timeout=5
        )
        return response.status_code == 200
    except:
        return False

def generate_with_retry(agent, prompt, max_retries=3):
    for attempt in range(max_retries):
        try:
            response = agent.step(prompt)
            return response.msgs[0].content
        except Exception as e:
            error_msg = str(e).lower()
            if ("rate" in error_msg or "limit" in error_msg) and attempt < max_retries - 1:
                wait_time = 2 ** attempt
                st.warning(f"⏳ Retrying in {wait_time}s...")
                time.sleep(wait_time)
                continue
            raise e
    return None

def reset_post_state():
    st.session_state.post_ready = False
    st.session_state.generated_post = ""
    st.session_state.uploaded_media = None
    st.session_state.media_type = None
    st.session_state.last_post_url = None
    st.session_state.last_post_urn = None

def get_linkedin_post_url(post_urn):
    if not post_urn:
        return None
    try:
        encoded_urn = requests.utils.quote(post_urn, safe='')
        return f"https://www.linkedin.com/feed/update/{encoded_urn}"
    except:
        return None

def get_linkedin_activity_url(post_urn):
    if not post_urn:
        return None
    try:
        post_id = post_urn.split(':')[-1]
        return f"https://www.linkedin.com/feed/update/urn:li:activity:{post_id}"
    except:
        return None

def get_linkedin_profile_url(user_urn=None, vanity_name=None):
    if vanity_name:
        return f"https://www.linkedin.com/in/{vanity_name}/"
    elif user_urn:
        user_id = user_urn.split(':')[-1] if user_urn else None
        if user_id:
            return f"https://www.linkedin.com/in/{user_id}/"
    return "https://www.linkedin.com/in/me/"

def get_linkedin_feed_url():
    return "https://www.linkedin.com/feed/"

def get_vanity_name(access_token):
    if not access_token:
        return None
    try:
        headers = {
            'Authorization': f'Bearer {access_token}',
            'X-Restli-Protocol-Version': '2.0.0'
        }
        response = linkedin_session.get(
            'https://api.linkedin.com/v2/me?projection=(id,vanityName)',
            headers=headers,
            timeout=10
        )
        if response.status_code == 200:
            data = response.json()
            return data.get('vanityName')
    except:
        pass
    return None

st.set_page_config(
    page_title="LinkedIn AI Automation • Groq + CAMEL-AI",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=Poppins:wght@600;700&display=swap');
    
    * { font-family: 'Inter', sans-serif; }
    .main { background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%); }
    
    .header-container {
        background: linear-gradient(135deg, #0077B5 0%, #00A0DC 50%, #0077B5 100%);
        background-size: 200% 200%;
        animation: gradientShift 8s ease infinite;
        padding: 2.5rem 2rem;
        border-radius: 20px;
        margin-bottom: 2.5rem;
        box-shadow: 0 15px 40px rgba(0,119,181,0.4);
        border: 1px solid rgba(255,255,255,0.2);
        position: relative;
        overflow: hidden;
    }
    
    .header-container::before {
        content: '';
        position: absolute;
        top: -50%;
        left: -50%;
        width: 200%;
        height: 200%;
        background: radial-gradient(circle, rgba(255,255,255,0.1) 0%, transparent 70%);
        animation: rotate 20s linear infinite;
    }
    
    @keyframes gradientShift {
        0% { background-position: 0% 50%; }
        50% { background-position: 100% 50%; }
        100% { background-position: 0% 50%; }
    }
    
    @keyframes rotate {
        from { transform: rotate(0deg); }
        to { transform: rotate(360deg); }
    }
    
    .logo-section { text-align: center; margin-bottom: 1.5rem; position: relative; z-index: 1; }
    
    .logo-badge {
        display: inline-flex;
        align-items: center;
        gap: 12px;
        background: rgba(255,255,255,0.95);
        padding: 0.8rem 2rem;
        border-radius: 50px;
        box-shadow: 0 8px 25px rgba(0,0,0,0.15);
        font-weight: 700;
        font-size: 1.1rem;
        margin-bottom: 1rem;
    }
    
    .logo-groq { color: #FF6B6B; font-weight: 800; font-size: 1.2rem; }
    .logo-plus { color: #666; font-weight: 400; }
    .logo-camel { color: #FF9F43; font-weight: 800; font-size: 1.2rem; }
    .logo-linkedin { color: #0077B5; font-weight: 800; font-size: 1.2rem; }
    
    .main-header {
        font-family: 'Poppins', sans-serif;
        font-size: 3.5rem;
        font-weight: 800;
        color: white;
        text-align: center;
        margin: 0;
        text-shadow: 0 4px 15px rgba(0,0,0,0.3);
        position: relative;
        z-index: 1;
    }
    
    .sub-header {
        text-align: center;
        color: rgba(255,255,255,0.95);
        font-size: 1.2rem;
        margin-top: 1rem;
        position: relative;
        z-index: 1;
    }
    
    .branding {
        text-align: center;
        color: rgba(255,255,255,0.9);
        font-size: 1rem;
        margin-top: 1.5rem;
        padding-top: 1.5rem;
        border-top: 2px solid rgba(255,255,255,0.25);
        position: relative;
        z-index: 1;
    }
    
    .branding a { color: #FFD700; text-decoration: none; font-weight: 700; }
    
    .post-box {
        padding: 2.5rem;
        background: linear-gradient(135deg, #ffffff 0%, #f8f9fa 100%);
        border-left: 8px solid #0077B5;
        border-radius: 15px;
        margin: 1.5rem 0;
        white-space: pre-wrap;
        box-shadow: 0 8px 30px rgba(0,0,0,0.12);
        line-height: 1.9;
        font-size: 1.08rem;
    }
    
    .success-box {
        padding: 2rem;
        background: linear-gradient(135deg, #d4edda 0%, #c3e6cb 100%);
        border-left: 8px solid #28a745;
        border-radius: 12px;
        margin: 1.5rem 0;
        text-align: center;
    }
    
    .success-box h2 {
        color: #155724;
        margin-bottom: 1rem;
    }
    
    .success-box p {
        color: #155724;
        margin-bottom: 0.5rem;
    }
    
    .view-post-btn {
        display: inline-block;
        background: linear-gradient(135deg, #0077B5 0%, #00A0DC 100%);
        color: white !important;
        padding: 12px 30px;
        border-radius: 25px;
        text-decoration: none;
        font-weight: 700;
        margin: 10px 5px;
        box-shadow: 0 4px 15px rgba(0,119,181,0.3);
        transition: transform 0.2s, box-shadow 0.2s;
    }
    
    .view-post-btn:hover {
        transform: translateY(-2px);
        box-shadow: 0 6px 20px rgba(0,119,181,0.4);
    }
    
    .view-profile-btn {
        display: inline-block;
        background: linear-gradient(135deg, #28a745 0%, #20c997 100%);
        color: white !important;
        padding: 12px 30px;
        border-radius: 25px;
        text-decoration: none;
        font-weight: 700;
        margin: 10px 5px;
        box-shadow: 0 4px 15px rgba(40,167,69,0.3);
        transition: transform 0.2s, box-shadow 0.2s;
    }
    
    .view-profile-btn:hover {
        transform: translateY(-2px);
        box-shadow: 0 6px 20px rgba(40,167,69,0.4);
    }
    
    .error-box {
        background: linear-gradient(135deg, #f8d7da 0%, #f5c6cb 100%);
        padding: 1.5rem;
        border-radius: 12px;
        border-left: 8px solid #dc3545;
        margin: 1.5rem 0;
    }
    
    .video-info {
        background: linear-gradient(135deg, #e8f5e9 0%, #c8e6c9 100%);
        padding: 1rem;
        border-radius: 10px;
        border-left: 5px solid #4caf50;
        margin: 1rem 0;
    }
    
    .upload-progress {
        background: linear-gradient(135deg, #e3f2fd 0%, #bbdefb 100%);
        padding: 1rem;
        border-radius: 10px;
        border-left: 5px solid #2196F3;
        margin: 1rem 0;
    }
    
    .status-badge {
        display: inline-block;
        padding: 0.6rem 1.3rem;
        border-radius: 25px;
        font-weight: 700;
        font-size: 0.95rem;
        margin: 0.5rem;
    }
    
    .status-success { background: linear-gradient(135deg, #d4edda 0%, #a3d9a5 100%); color: #155724; border: 2px solid #28a745; }
    .status-warning { background: linear-gradient(135deg, #fff3cd 0%, #ffe69c 100%); color: #856404; border: 2px solid #ffc107; }
    .status-error { background: linear-gradient(135deg, #f8d7da 0%, #f5c6cb 100%); color: #721c24; border: 2px solid #dc3545; }
    
    .feature-card {
        background: linear-gradient(135deg, #ffffff 0%, #f8f9fa 100%);
        padding: 1.5rem;
        border-radius: 15px;
        box-shadow: 0 8px 25px rgba(0,0,0,0.1);
        margin: 1rem 0;
    }
    
    .tips-box {
        background: linear-gradient(135deg, #e3f2fd 0%, #bbdefb 100%);
        padding: 1.5rem;
        border-radius: 12px;
        border-left: 8px solid #2196F3;
        margin: 1rem 0;
    }
    
    .tips-box h4 { margin-top: 0; color: #1976D2; font-weight: 700; }
    
    .section-header {
        font-family: 'Poppins', sans-serif;
        font-weight: 700;
        font-size: 1.8rem;
        color: #0077B5;
        margin: 2rem 0 1rem 0;
        padding-bottom: 0.5rem;
        border-bottom: 3px solid #0077B5;
    }
    
    .sidebar-header {
        font-weight: 700;
        font-size: 1.3rem;
        color: #0077B5;
        margin: 1.5rem 0 1rem 0;
        padding: 0.5rem;
        background: linear-gradient(135deg, #e3f2fd 0%, #bbdefb 100%);
        border-radius: 8px;
        text-align: center;
    }
    
    .stButton>button {
        border-radius: 10px;
        font-weight: 700;
        border: none;
        padding: 0.75rem 1.5rem;
        font-size: 1rem;
    }
    
    .profile-card {
        background: linear-gradient(135deg, #ffffff 0%, #f0f8ff 100%);
        padding: 2rem;
        border-radius: 20px;
        box-shadow: 0 10px 40px rgba(0,119,181,0.15);
        border: 2px solid #0077B5;
        text-align: center;
        margin: 1rem 0;
    }
    
    .profile-photo {
        width: 150px;
        height: 150px;
        border-radius: 50%;
        border: 5px solid #0077B5;
        box-shadow: 0 8px 25px rgba(0,0,0,0.15);
        object-fit: cover;
        margin-bottom: 1rem;
    }
    
    .profile-name {
        font-size: 1.8rem;
        font-weight: 700;
        color: #0077B5;
        margin: 0.5rem 0;
    }
    
    .profile-headline {
        font-size: 1.1rem;
        color: #666;
        margin-bottom: 1rem;
    }
    
    .delete-warning {
        background: linear-gradient(135deg, #fff3cd 0%, #ffeaa7 100%);
        padding: 1.5rem;
        border-radius: 12px;
        border-left: 8px solid #ffc107;
        margin: 1rem 0;
    }
    
    .post-history-item {
        background: white;
        padding: 1rem;
        border-radius: 10px;
        margin: 0.5rem 0;
        border-left: 4px solid #0077B5;
        box-shadow: 0 2px 10px rgba(0,0,0,0.05);
    }
    
    .post-live-indicator {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        background: linear-gradient(135deg, #28a745 0%, #20c997 100%);
        color: white;
        padding: 8px 16px;
        border-radius: 20px;
        font-weight: 600;
        font-size: 0.9rem;
        animation: pulse 2s infinite;
    }
    
    @keyframes pulse {
        0% { box-shadow: 0 0 0 0 rgba(40, 167, 69, 0.4); }
        70% { box-shadow: 0 0 0 10px rgba(40, 167, 69, 0); }
        100% { box-shadow: 0 0 0 0 rgba(40, 167, 69, 0); }
    }
    
    .link-box {
        background: linear-gradient(135deg, #e8f5e9 0%, #c8e6c9 100%);
        padding: 1.5rem;
        border-radius: 12px;
        border-left: 5px solid #28a745;
        margin: 1rem 0;
        text-align: center;
    }
    
    .link-box a {
        color: #0077B5;
        text-decoration: none;
        font-weight: 600;
        word-break: break-all;
    }
    
    .link-box a:hover {
        text-decoration: underline;
    }
    </style>
""", unsafe_allow_html=True)

def init_session_state():
    defaults = {
        'agent': None,
        'linkedin_toolkit': None,
        'generated_post': "",
        'post_ready': False,
        'system_initialized': False,
        'uploaded_media': None,
        'media_type': None,
        'messages': [],
        'linkedin_token': "",
        'user_urn': None,
        'connection_verified': False,
        'user_profile': None,
        'post_history': [],
        'last_post_url': None,
        'last_post_urn': None,
        'vanity_name': None,
        'profile_url': None,
        'show_success': False
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

init_session_state()

def get_user_profile(access_token):
    if not access_token:
        return None
    try:
        headers = {
            'Authorization': f'Bearer {access_token}',
            'X-Restli-Protocol-Version': '2.0.0'
        }
        try:
            response = linkedin_session.get('https://api.linkedin.com/v2/userinfo', headers=headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                user_id = data.get('sub')
                if user_id:
                    return f"urn:li:person:{user_id}"
        except:
            pass
        try:
            response = linkedin_session.get('https://api.linkedin.com/v2/me', headers=headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                user_id = data.get('id')
                if user_id:
                    return f"urn:li:person:{user_id}"
        except:
            pass
        return None
    except:
        return None

def get_full_profile(access_token):
    if not access_token:
        return None
    try:
        headers = {
            'Authorization': f'Bearer {access_token}',
            'X-Restli-Protocol-Version': '2.0.0'
        }
        
        profile_data = {
            'name': 'LinkedIn User',
            'email': '',
            'picture': '',
            'headline': 'Professional',
            'id': '',
            'vanity_name': None
        }
        
        try:
            response = linkedin_session.get('https://api.linkedin.com/v2/userinfo', headers=headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                profile_data['name'] = data.get('name', 'LinkedIn User')
                profile_data['email'] = data.get('email', '')
                profile_data['picture'] = data.get('picture', '')
                profile_data['id'] = data.get('sub', '')
        except:
            pass
        
        try:
            response = linkedin_session.get(
                'https://api.linkedin.com/v2/me?projection=(id,firstName,lastName,vanityName,profilePicture(displayImage~:playableStreams))',
                headers=headers,
                timeout=10
            )
            if response.status_code == 200:
                data = response.json()
                first_name = data.get('firstName', {}).get('localized', {})
                last_name = data.get('lastName', {}).get('localized', {})
                
                fn = list(first_name.values())[0] if first_name else ''
                ln = list(last_name.values())[0] if last_name else ''
                if fn or ln:
                    profile_data['name'] = f"{fn} {ln}".strip()
                
                profile_data['id'] = data.get('id', profile_data['id'])
                profile_data['vanity_name'] = data.get('vanityName')
                
                try:
                    elements = data.get('profilePicture', {}).get('displayImage~', {}).get('elements', [])
                    if elements:
                        for elem in elements:
                            identifiers = elem.get('identifiers', [])
                            if identifiers:
                                profile_data['picture'] = identifiers[0].get('identifier', '')
                                break
                except:
                    pass
        except:
            pass
        
        return profile_data
    except:
        return None

def delete_linkedin_post(access_token, post_urn):
    if not access_token or not post_urn:
        return False, "Missing token or post URN"
    
    try:
        headers = {
            'Authorization': f'Bearer {access_token}',
            'X-Restli-Protocol-Version': '2.0.0'
        }
        
        if 'ugcPost' in post_urn:
            encoded_urn = requests.utils.quote(post_urn, safe='')
            url = f'https://api.linkedin.com/v2/ugcPosts/{encoded_urn}'
        elif 'share' in post_urn:
            encoded_urn = requests.utils.quote(post_urn, safe='')
            url = f'https://api.linkedin.com/v2/shares/{encoded_urn}'
        else:
            encoded_urn = requests.utils.quote(post_urn, safe='')
            url = f'https://api.linkedin.com/v2/ugcPosts/{encoded_urn}'
        
        response = linkedin_session.delete(url, headers=headers, timeout=15)
        
        if response.status_code in [200, 204]:
            return True, "Post deleted successfully!"
        elif response.status_code == 404:
            return False, "Post not found. Check the URN."
        elif response.status_code == 403:
            return False, "Permission denied. You can only delete your own posts."
        else:
            return False, f"Delete failed: {response.status_code}"
            
    except Exception as e:
        return False, f"Error: {str(e)}"

def register_image_upload(access_token, user_urn):
    try:
        headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json',
            'X-Restli-Protocol-Version': '2.0.0'
        }
        register_data = {
            "registerUploadRequest": {
                "recipes": ["urn:li:digitalmediaRecipe:feedshare-image"],
                "owner": user_urn,
                "serviceRelationships": [{"relationshipType": "OWNER", "identifier": "urn:li:userGeneratedContent"}]
            }
        }
        response = linkedin_session.post('https://api.linkedin.com/v2/assets?action=registerUpload', headers=headers, json=register_data, timeout=15)
        if response.status_code in [200, 201]:
            data = response.json()
            upload_url = data['value']['uploadMechanism']['com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest']['uploadUrl']
            asset = data['value']['asset']
            return upload_url, asset
        return None, None
    except:
        return None, None

def upload_image_to_linkedin(upload_url, image_data, access_token):
    try:
        headers = {'Authorization': f'Bearer {access_token}', 'Content-Type': 'application/octet-stream'}
        response = requests.put(upload_url, headers=headers, data=image_data, timeout=60)
        return response.status_code in [200, 201]
    except:
        return False

def create_post_with_image(access_token, user_urn, text, asset_urn):
    try:
        headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json',
            'X-Restli-Protocol-Version': '2.0.0'
        }
        post_data = {
            "author": user_urn,
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": {
                    "shareCommentary": {"text": text},
                    "shareMediaCategory": "IMAGE",
                    "media": [{"status": "READY", "media": asset_urn}]
                }
            },
            "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"}
        }
        response = linkedin_session.post('https://api.linkedin.com/v2/ugcPosts', headers=headers, json=post_data, timeout=30)
        if response.status_code in [200, 201]:
            result = response.json()
            post_urn = result.get('id', '')
            post_url = get_linkedin_post_url(post_urn)
            if post_urn:
                st.session_state.post_history.append({
                    'urn': post_urn,
                    'url': post_url,
                    'text': text[:100] + '...' if len(text) > 100 else text,
                    'type': 'image',
                    'time': time.strftime('%Y-%m-%d %H:%M')
                })
                st.session_state.last_post_urn = post_urn
                st.session_state.last_post_url = post_url
            return True, result
        return False, f"Failed: {response.status_code} - {response.text}"
    except Exception as e:
        return False, str(e)

def register_video_upload(access_token, user_urn, file_size):
    try:
        headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json',
            'X-Restli-Protocol-Version': '2.0.0'
        }
        register_data = {
            "registerUploadRequest": {
                "recipes": ["urn:li:digitalmediaRecipe:feedshare-video"],
                "owner": user_urn,
                "serviceRelationships": [{"relationshipType": "OWNER", "identifier": "urn:li:userGeneratedContent"}],
                "supportedUploadMechanism": ["SINGLE_REQUEST_UPLOAD"],
                "fileSize": file_size
            }
        }
        response = linkedin_session.post('https://api.linkedin.com/v2/assets?action=registerUpload', headers=headers, json=register_data, timeout=30)
        if response.status_code in [200, 201]:
            data = response.json()
            upload_url = data['value']['uploadMechanism']['com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest']['uploadUrl']
            asset = data['value']['asset']
            return upload_url, asset
        st.error(f"Video register failed: {response.status_code}")
        return None, None
    except Exception as e:
        st.error(f"Video register error: {str(e)}")
        return None, None

def upload_video_to_linkedin(upload_url, video_data, access_token, file_size_mb):
    try:
        headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/octet-stream',
        }
        
        timeout_seconds = max(300, int(file_size_mb * 5))
        
        response = requests.put(
            upload_url,
            headers=headers,
            data=video_data,
            timeout=timeout_seconds
        )
        
        if response.status_code in [200, 201]:
            return True
        else:
            st.error(f"Video upload failed: {response.status_code}")
            return False
    except requests.exceptions.Timeout:
        st.error("Video upload timeout - try smaller file or better connection")
        return False
    except Exception as e:
        st.error(f"Video upload error: {str(e)}")
        return False

def check_video_status(access_token, asset_urn):
    try:
        headers = {'Authorization': f'Bearer {access_token}', 'X-Restli-Protocol-Version': '2.0.0'}
        asset_id = asset_urn.split(':')[-1]
        response = linkedin_session.get(f'https://api.linkedin.com/v2/assets/{asset_id}', headers=headers, timeout=10)
        if response.status_code == 200:
            data = response.json()
            recipes = data.get('recipes', [])
            for recipe in recipes:
                status = recipe.get('status')
                if status:
                    return status
            return "PROCESSING"
        return "PROCESSING"
    except:
        return "PROCESSING"

def wait_for_video_processing(access_token, asset_urn, status_placeholder, max_wait=120):
    start_time = time.time()
    check_count = 0
    
    while time.time() - start_time < max_wait:
        status = check_video_status(access_token, asset_urn)
        check_count += 1
        elapsed = int(time.time() - start_time)
        
        if status == "AVAILABLE":
            status_placeholder.success("✅ Video processed successfully!")
            return True
        elif status == "ERROR":
            status_placeholder.error("❌ Video processing failed")
            return False
        else:
            status_placeholder.info(f"⏳ Processing video... ({elapsed}s)")
        
        time.sleep(3)
    
    status_placeholder.warning("⏳ Processing taking long, posting anyway...")
    return True

def create_post_with_video(access_token, user_urn, text, asset_urn):
    try:
        headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json',
            'X-Restli-Protocol-Version': '2.0.0'
        }
        post_data = {
            "author": user_urn,
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": {
                    "shareCommentary": {"text": text},
                    "shareMediaCategory": "VIDEO",
                    "media": [{"status": "READY", "media": asset_urn}]
                }
            },
            "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"}
        }
        response = linkedin_session.post('https://api.linkedin.com/v2/ugcPosts', headers=headers, json=post_data, timeout=60)
        if response.status_code in [200, 201]:
            result = response.json()
            post_urn = result.get('id', '')
            post_url = get_linkedin_post_url(post_urn)
            if post_urn:
                st.session_state.post_history.append({
                    'urn': post_urn,
                    'url': post_url,
                    'text': text[:100] + '...' if len(text) > 100 else text,
                    'type': 'video',
                    'time': time.strftime('%Y-%m-%d %H:%M')
                })
                st.session_state.last_post_urn = post_urn
                st.session_state.last_post_url = post_url
            return True, result
        return False, f"Failed: {response.status_code} - {response.text}"
    except Exception as e:
        return False, str(e)

def create_text_only_post(access_token, user_urn, text):
    try:
        headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json',
            'X-Restli-Protocol-Version': '2.0.0'
        }
        post_data = {
            "author": user_urn,
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": {
                    "shareCommentary": {"text": text},
                    "shareMediaCategory": "NONE"
                }
            },
            "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"}
        }
        response = linkedin_session.post('https://api.linkedin.com/v2/ugcPosts', headers=headers, json=post_data, timeout=30)
        if response.status_code in [200, 201]:
            result = response.json()
            post_urn = result.get('id', '')
            post_url = get_linkedin_post_url(post_urn)
            if post_urn:
                st.session_state.post_history.append({
                    'urn': post_urn,
                    'url': post_url,
                    'text': text[:100] + '...' if len(text) > 100 else text,
                    'type': 'text',
                    'time': time.strftime('%Y-%m-%d %H:%M')
                })
                st.session_state.last_post_urn = post_urn
                st.session_state.last_post_url = post_url
            return True, result
        return False, f"Failed: {response.status_code} - {response.text}"
    except Exception as e:
        return False, str(e)

def post_to_linkedin_with_media(access_token, text, media_file=None, media_type=None):
    status_placeholder = st.empty()
    
    status_placeholder.info("🔄 Checking connection...")
    if not check_linkedin_connection(access_token):
        status_placeholder.error("❌ Connection failed")
        return False, "Connection failed. Check internet and token."
    
    status_placeholder.info("🔄 Getting user profile...")
    user_urn = get_user_profile(access_token)
    if not user_urn:
        status_placeholder.error("❌ Could not get profile")
        return False, "Could not get user profile."
    
    if not media_file or not media_type:
        status_placeholder.info("📝 Creating text post...")
        result = create_text_only_post(access_token, user_urn, text)
        status_placeholder.empty()
        return result
    
    if media_type == "image":
        status_placeholder.info("📷 Registering image upload...")
        upload_url, asset_urn = register_image_upload(access_token, user_urn)
        if not upload_url:
            status_placeholder.warning("⚠️ Image upload failed, posting text only...")
            result = create_text_only_post(access_token, user_urn, text)
            status_placeholder.empty()
            return result
        
        status_placeholder.info("📷 Uploading image...")
        media_file.seek(0)
        image_data = media_file.read()
        if not upload_image_to_linkedin(upload_url, image_data, access_token):
            status_placeholder.warning("⚠️ Image upload failed, posting text only...")
            result = create_text_only_post(access_token, user_urn, text)
            status_placeholder.empty()
            return result
        
        status_placeholder.info("📷 Creating image post...")
        result = create_post_with_image(access_token, user_urn, text, asset_urn)
        status_placeholder.empty()
        return result
    
    elif media_type == "video":
        media_file.seek(0, 2)
        file_size = media_file.tell()
        media_file.seek(0)
        file_size_mb = file_size / (1024 * 1024)
        
        if file_size > 200 * 1024 * 1024:
            status_placeholder.error("❌ Video too large (max 200MB)")
            return False, "Video exceeds 200MB limit"
        
        status_placeholder.info(f"🎬 Registering video upload ({file_size_mb:.1f}MB)...")
        upload_url, asset_urn = register_video_upload(access_token, user_urn, file_size)
        if not upload_url:
            status_placeholder.warning("⚠️ Video registration failed, posting text only...")
            result = create_text_only_post(access_token, user_urn, text)
            status_placeholder.empty()
            return result
        
        status_placeholder.info(f"🎬 Uploading video ({file_size_mb:.1f}MB)... Please wait...")
        video_data = media_file.read()
        
        upload_success = upload_video_to_linkedin(upload_url, video_data, access_token, file_size_mb)
        
        if not upload_success:
            status_placeholder.warning("⚠️ Video upload failed, posting text only...")
            result = create_text_only_post(access_token, user_urn, text)
            status_placeholder.empty()
            return result
        
        status_placeholder.info("🎬 Video uploaded! Waiting for LinkedIn to process...")
        
        processing_success = wait_for_video_processing(access_token, asset_urn, status_placeholder, max_wait=120)
        
        status_placeholder.info("🎬 Creating video post...")
        result = create_post_with_video(access_token, user_urn, text, asset_urn)
        status_placeholder.empty()
        return result
    
    result = create_text_only_post(access_token, user_urn, text)
    status_placeholder.empty()
    return result

def initialize_agent(api_key):
    try:
        os.environ["GROQ_API_KEY"] = api_key
        model = ModelFactory.create(
            model_platform=ModelPlatformType.GROQ,
            model_type=ModelType.GROQ_LLAMA_3_3_70B,
            model_config_dict=GroqConfig(temperature=0.7).as_dict(),
        )
        agent = ChatAgent(
            system_message="""You are an expert LinkedIn content strategist. Create engaging posts that:
            - Hook readers in the first line
            - Deliver clear value and insights
            - Use 3-5 strategic hashtags at the end
            - Include compelling call-to-action
            - Use emojis purposefully
            - Are authentic and professional
            - Break up text with line breaks""",
            model=model,
        )
        return agent
    except Exception as e:
        st.error(f"❌ Agent initialization failed: {str(e)}")
        return None

def initialize_linkedin(access_token):
    try:
        os.environ["LINKEDIN_ACCESS_TOKEN"] = access_token
        toolkit = LinkedInToolkit()
        tools = toolkit.get_tools()
        if tools:
            return toolkit
        return None
    except:
        return None

st.markdown("""
    <div class="header-container">
        <div class="logo-section">
            <div class="logo-badge">
                <span class="logo-groq">⚡ Groq</span>
                <span class="logo-plus">+</span>
                <span class="logo-camel">🐫 CAMEL-AI</span>
                <span class="logo-plus">+</span>
                <span class="logo-linkedin">🔗 LinkedIn</span>
            </div>
        </div>
        <h1 class="main-header">🚀 LinkedIn AI Automation</h1>
        <p class="sub-header">Generate & Post Professional Content with AI • 📷 Images • 🎬 Videos • ⚡ Lightning Fast</p>
        <div class="branding">
            Powered by <strong>Groq AI</strong> • Built with <strong>CAMEL-AI Framework</strong> • 
            <a href="https://github.com/HarshS99" target="_blank">👨‍💻 GitHub</a>
        </div>
    </div>
""", unsafe_allow_html=True)

with st.sidebar:
    st.markdown('<div class="sidebar-header">⚙️ Configuration</div>', unsafe_allow_html=True)
    st.markdown("---")
    
    groq_api_key = st.text_input("Groq API Key", value=os.getenv("GROQ_API_KEY", ""), type="password", key="groq_key")
    linkedin_token = st.text_input("LinkedIn Access Token", value=os.getenv("LINKEDIN_ACCESS_TOKEN", ""), type="password", key="linkedin_token_input")
    
    st.markdown("---")
    
    if st.button("🚀 **Initialize**", type="primary", use_container_width=True):
        if not groq_api_key:
            st.error("❌ Groq API Key required!")
        else:
            with st.spinner("🔄 Initializing..."):
                st.session_state.agent = initialize_agent(groq_api_key)
                if linkedin_token:
                    st.session_state.linkedin_token = linkedin_token
                    st.session_state.linkedin_toolkit = initialize_linkedin(linkedin_token)
                    user_urn = get_user_profile(linkedin_token)
                    if user_urn:
                        st.session_state.user_urn = user_urn
                        st.session_state.connection_verified = True
                        st.session_state.user_profile = get_full_profile(linkedin_token)
                        if st.session_state.user_profile:
                            st.session_state.vanity_name = st.session_state.user_profile.get('vanity_name')
                        st.session_state.profile_url = get_linkedin_profile_url(
                            user_urn, 
                            st.session_state.vanity_name
                        )
                    else:
                        st.session_state.user_urn = None
                        st.session_state.connection_verified = False
                else:
                    st.session_state.linkedin_toolkit = None
                    st.session_state.linkedin_token = ""
                    st.session_state.connection_verified = False
                
                if st.session_state.agent:
                    st.session_state.system_initialized = True
                    st.success("✅ Groq AI Ready!")
                    if st.session_state.linkedin_token and st.session_state.user_urn:
                        st.success("✅ LinkedIn Connected!")
                    elif st.session_state.linkedin_token:
                        st.warning("⚠️ LinkedIn issue")
                else:
                    st.error("❌ Failed!")
    
    st.markdown("---")
    st.markdown('<div class="sidebar-header">📊 Status</div>', unsafe_allow_html=True)
    
    if st.session_state.agent:
        st.markdown('<span class="status-badge status-success">⚡ Groq: Active</span>', unsafe_allow_html=True)
    else:
        st.markdown('<span class="status-badge status-error">⚡ Groq: Inactive</span>', unsafe_allow_html=True)
    
    if st.session_state.linkedin_token and st.session_state.connection_verified:
        st.markdown('<span class="status-badge status-success">🔗 LinkedIn: Connected</span>', unsafe_allow_html=True)
        if st.session_state.profile_url:
            st.markdown(f"[👤 View Profile]({st.session_state.profile_url})")
    else:
        st.markdown('<span class="status-badge status-error">🔗 LinkedIn: Not Connected</span>', unsafe_allow_html=True)
    
    st.markdown("---")
    st.markdown('<div class="sidebar-header">📁 Media</div>', unsafe_allow_html=True)
    st.markdown("""
    <div class="feature-card">
        <strong>📷 Images:</strong> JPG, PNG, GIF (Max 10MB)<br><br>
        <strong>🎬 Videos:</strong> MP4, MOV (Max 200MB)
    </div>
    """, unsafe_allow_html=True)
    
    if st.session_state.connection_verified:
        st.markdown("---")
        st.markdown('<div class="sidebar-header">🔗 Quick Links</div>', unsafe_allow_html=True)
        st.markdown(f"""
        <div class="feature-card">
            <a href="{get_linkedin_feed_url()}" target="_blank">📰 LinkedIn Feed</a><br><br>
            <a href="{st.session_state.profile_url or get_linkedin_profile_url()}" target="_blank">👤 My Profile</a><br><br>
            <a href="https://www.linkedin.com/feed/following/" target="_blank">👥 Following</a>
        </div>
        """, unsafe_allow_html=True)

tab1, tab2, tab3, tab4 = st.tabs(["✍️ **Create Post**", "🗑️ **Delete Post**", "👤 **Profile**", "🤖 **AI Chat**"])

with tab1:
    st.markdown('<h2 class="section-header">✍️ Create LinkedIn Post</h2>', unsafe_allow_html=True)
    
    if st.session_state.show_success and st.session_state.last_post_url:
        profile_url = st.session_state.profile_url or get_linkedin_profile_url()
        
        st.markdown(f"""
        <div class="success-box">
            <h2>🎉 POST PUBLISHED SUCCESSFULLY!</h2>
            <p>Your post is now live on LinkedIn!</p>
            <div class="post-live-indicator">
                <span>🟢</span> LIVE ON LINKEDIN
            </div>
            <br><br>
            <a href="{st.session_state.last_post_url}" target="_blank" class="view-post-btn">
                👁️ View Post on LinkedIn
            </a>
            <a href="{profile_url}" target="_blank" class="view-profile-btn">
                👤 View My Profile
            </a>
            <br><br>
            <div class="link-box">
                <strong>📎 Direct Post Link:</strong><br>
                <a href="{st.session_state.last_post_url}" target="_blank">{st.session_state.last_post_url}</a>
            </div>
        </div>
        """, unsafe_allow_html=True)
        
        col_new, col_another = st.columns(2)
        with col_new:
            if st.button("✨ Create New Post", type="primary", use_container_width=True):
                st.session_state.show_success = False
                reset_post_state()
                st.rerun()
        with col_another:
            if st.button("📋 Copy Post Link", use_container_width=True):
                st.code(st.session_state.last_post_url)
    else:
        col1, col2 = st.columns([2, 1])
        
        with col1:
            post_topic = st.text_input("What do you want to talk about?", placeholder="E.g., AI in healthcare, Leadership tips...", key="post_topic")
            
            col_tone, col_length = st.columns(2)
            with col_tone:
                tone = st.selectbox("🎭 Tone", ["Professional", "Casual", "Inspirational", "Educational", "Storytelling"], key="tone")
            with col_length:
                length = st.selectbox("📏 Length", ["Short (50-100 words)", "Medium (100-200 words)", "Long (200-300 words)"], key="length")
            
            with st.expander("⚙️ Advanced"):
                include_cta = st.checkbox("Include CTA", value=True)
                include_hashtags = st.checkbox("Include Hashtags", value=True)
                include_emojis = st.checkbox("Include Emojis", value=True)
                target_audience = st.text_input("Target Audience", placeholder="E.g., Tech professionals...")
        
        with col2:
            st.markdown("""
            <div class="tips-box">
                <h4>💡 Tips</h4>
                ✅ Hook in first line<br>
                ✅ Share insights<br>
                ✅ Tell stories<br>
                ✅ Ask questions
            </div>
            """, unsafe_allow_html=True)
        
        st.markdown("---")
        st.markdown("#### 📸 **Media**")
        
        col_m1, col_m2 = st.columns([2, 1])
        
        with col_m1:
            media_option = st.radio("Type:", ["📝 Text Only", "📷 Image", "🎬 Video"], horizontal=True, key="media_opt")
            
            if media_option == "📷 Image":
                uploaded_file = st.file_uploader("Upload Image", type=["jpg", "jpeg", "png", "gif"], key="img_upload")
                if uploaded_file:
                    file_size = get_file_size_mb(uploaded_file)
                    if file_size > 10:
                        st.error(f"❌ Too large! {file_size:.1f}MB (Max: 10MB)")
                        st.session_state.uploaded_media = None
                        st.session_state.media_type = None
                    else:
                        st.session_state.uploaded_media = uploaded_file
                        st.session_state.media_type = "image"
                        st.success(f"✅ Ready: {file_size:.2f}MB")
                else:
                    st.session_state.uploaded_media = None
                    st.session_state.media_type = None
                    
            elif media_option == "🎬 Video":
                uploaded_file = st.file_uploader("Upload Video", type=["mp4", "mov", "avi"], key="vid_upload")
                if uploaded_file:
                    file_size = get_file_size_mb(uploaded_file)
                    if file_size > 200:
                        st.error(f"❌ Too large! {file_size:.1f}MB (Max: 200MB)")
                        st.session_state.uploaded_media = None
                        st.session_state.media_type = None
                    else:
                        st.session_state.uploaded_media = uploaded_file
                        st.session_state.media_type = "video"
                        st.markdown(f'<div class="video-info">🎬 <strong>{uploaded_file.name}</strong> • {file_size:.1f}MB ✅</div>', unsafe_allow_html=True)
                else:
                    st.session_state.uploaded_media = None
                    st.session_state.media_type = None
            else:
                st.session_state.uploaded_media = None
                st.session_state.media_type = None
        
        with col_m2:
            st.markdown("**Preview**")
            if st.session_state.uploaded_media:
                if st.session_state.media_type == "image":
                    st.image(st.session_state.uploaded_media, use_container_width=True)
                elif st.session_state.media_type == "video":
                    st.video(st.session_state.uploaded_media)
            else:
                st.info("📝 Text only")
        
        st.markdown("---")
        
        col_g1, col_g2 = st.columns([3, 1])
        
        with col_g1:
            if st.button("✨ **Generate Post**", type="primary", use_container_width=True):
                if not st.session_state.agent:
                    st.error("❌ Initialize system first!")
                elif not post_topic:
                    st.warning("⚠️ Enter a topic!")
                else:
                    with st.spinner("⚡ Generating..."):
                        try:
                            prompt = f"""Create a {tone.lower()} LinkedIn post about: {post_topic}
                            Length: {length}
                            Requirements:
                            - Attention-grabbing hook
                            - Authentic value
                            - Line breaks for readability
                            {"- 3-5 hashtags" if include_hashtags else ""}
                            {"- Clear CTA" if include_cta else ""}
                            {"- Strategic emojis" if include_emojis else ""}
                            {f"- Target: {target_audience}" if target_audience else ""}
                            """
                            content = generate_with_retry(st.session_state.agent, prompt)
                            if content:
                                st.session_state.generated_post = content
                                st.session_state.post_ready = True
                                st.success("✅ Generated!")
                            else:
                                st.error("❌ Failed. Try again.")
                        except Exception as e:
                            st.error(f"❌ Error: {str(e)}")
        
        with col_g2:
            if st.button("🔄 **Reset**", use_container_width=True):
                reset_post_state()
                st.rerun()
        
        if st.session_state.post_ready and st.session_state.generated_post:
            st.markdown("---")
            st.markdown("### 📝 **Your Post**")
            
            edited_post = st.text_area("Edit:", value=st.session_state.generated_post, height=250, key="editor")
            if edited_post != st.session_state.generated_post:
                st.session_state.generated_post = edited_post
            
            char_count = len(st.session_state.generated_post)
            st.info(f"📊 {char_count}/3000 characters")
            
            st.markdown(f'<div class="post-box">{st.session_state.generated_post}</div>', unsafe_allow_html=True)
            
            col_a, col_b, col_c = st.columns(3)
            
            with col_a:
                if st.button("📤 **PUBLISH**", type="primary", use_container_width=True):
                    if not st.session_state.linkedin_token:
                        st.error("❌ Connect LinkedIn first!")
                    elif not st.session_state.generated_post.strip():
                        st.error("❌ Post is empty!")
                    else:
                        success, result = post_to_linkedin_with_media(
                            st.session_state.linkedin_token,
                            st.session_state.generated_post,
                            st.session_state.uploaded_media,
                            st.session_state.media_type
                        )
                        if success:
                            st.session_state.show_success = True
                            st.session_state.post_ready = False
                            st.session_state.generated_post = ""
                            st.rerun()
                        else:
                            st.markdown(f'<div class="error-box"><h3>❌ Failed</h3><p>{result}</p></div>', unsafe_allow_html=True)
            
            with col_b:
                if st.button("🔄 **Regenerate**", use_container_width=True):
                    st.session_state.post_ready = False
                    st.session_state.generated_post = ""
                    st.rerun()
            
            with col_c:
                if st.button("📋 **Copy**", use_container_width=True):
                    st.code(st.session_state.generated_post, language=None)

with tab2:
    st.markdown('<h2 class="section-header">🗑️ Delete Post</h2>', unsafe_allow_html=True)
    
    if not st.session_state.linkedin_token:
        st.warning("⚠️ Connect LinkedIn first (use sidebar)")
    else:
        st.markdown("""
        <div class="delete-warning">
            <h4>⚠️ Warning</h4>
            <p>Deleting a post is permanent and cannot be undone.</p>
        </div>
        """, unsafe_allow_html=True)
        
        st.markdown("#### 📋 Recent Posts (This Session)")
        
        if st.session_state.post_history:
            for i, post in enumerate(reversed(st.session_state.post_history)):
                col1, col2, col3 = st.columns([2, 1, 1])
                with col1:
                    icon = "📝" if post['type'] == 'text' else "📷" if post['type'] == 'image' else "🎬"
                    st.markdown(f"""
                    <div class="post-history-item">
                        <strong>{icon} {post['time']}</strong><br>
                        <small>{post['text']}</small><br>
                        <code style="font-size: 0.8rem;">{post['urn']}</code>
                    </div>
                    """, unsafe_allow_html=True)
                with col2:
                    if post.get('url'):
                        st.markdown(f"[👁️ View]({post['url']})")
                with col3:
                    if st.button(f"🗑️ Delete", key=f"del_{i}"):
                        with st.spinner("Deleting..."):
                            success, msg = delete_linkedin_post(st.session_state.linkedin_token, post['urn'])
                            if success:
                                st.success(msg)
                                st.session_state.post_history = [p for p in st.session_state.post_history if p['urn'] != post['urn']]
                                st.rerun()
                            else:
                                st.error(msg)
        else:
            st.info("📭 No posts created in this session yet.")
        
        st.markdown("---")
        st.markdown("#### 🔗 Delete by URN")
        
        post_urn = st.text_input("Enter Post URN:", placeholder="urn:li:ugcPost:1234567890", key="delete_urn_input")
        
        if st.button("🗑️ **Delete Post**", type="primary"):
            if not post_urn:
                st.warning("⚠️ Please enter a Post URN")
            elif not post_urn.startswith("urn:li:"):
                st.error("❌ Invalid URN format")
            else:
                with st.spinner("🗑️ Deleting..."):
                    success, message = delete_linkedin_post(st.session_state.linkedin_token, post_urn)
                    if success:
                        st.success(message)
                    else:
                        st.error(message)

with tab3:
    st.markdown('<h2 class="section-header">👤 Profile</h2>', unsafe_allow_html=True)
    
    if not st.session_state.linkedin_token:
        st.warning("⚠️ Connect LinkedIn first (use sidebar)")
    else:
        if st.button("🔄 **Refresh Profile**", use_container_width=True):
            with st.spinner("Loading..."):
                st.session_state.user_profile = get_full_profile(st.session_state.linkedin_token)
                st.session_state.user_urn = get_user_profile(st.session_state.linkedin_token)
                if st.session_state.user_profile:
                    st.session_state.vanity_name = st.session_state.user_profile.get('vanity_name')
                    st.session_state.profile_url = get_linkedin_profile_url(
                        st.session_state.user_urn,
                        st.session_state.vanity_name
                    )
                    st.success("✅ Profile loaded!")
        
        if st.session_state.user_profile:
            profile = st.session_state.user_profile
            
            col_pic, col_info = st.columns([1, 2])
            
            with col_pic:
                if profile.get('picture'):
                    st.image(profile['picture'], width=150)
                else:
                    st.markdown("""
                    <div style="width: 150px; height: 150px; border-radius: 50%; background: linear-gradient(135deg, #0077B5, #00A0DC); 
                         display: flex; align-items: center; justify-content: center; margin: 0 auto;">
                        <span style="font-size: 4rem; color: white;">👤</span>
                    </div>
                    """, unsafe_allow_html=True)
            
            with col_info:
                profile_url = st.session_state.profile_url or get_linkedin_profile_url()
                st.markdown(f"""
                <div class="profile-card">
                    <h2 class="profile-name">{profile.get('name', 'LinkedIn User')}</h2>
                    <p>📧 {profile.get('email', 'Email not available')}</p>
                    <p>🆔 {profile.get('id', 'N/A')}</p>
                    <p>✅ Connected • {len(st.session_state.post_history)} posts this session</p>
                    <br>
                    <a href="{profile_url}" target="_blank" class="view-profile-btn">
                        👤 View My LinkedIn Profile
                    </a>
                </div>
                """, unsafe_allow_html=True)
            
            if st.session_state.user_urn:
                st.markdown(f"""
                <div class="feature-card">
                    <h4>🔗 User URN</h4>
                    <code>{st.session_state.user_urn}</code>
                </div>
                """, unsafe_allow_html=True)
            
            st.markdown("---")
            st.markdown("#### 🔗 Quick Links")
            
            col_link1, col_link2, col_link3 = st.columns(3)
            
            with col_link1:
                st.markdown(f"""
                <div class="link-box">
                    <strong>👤 My Profile</strong><br>
                    <a href="{profile_url}" target="_blank">Open Profile</a>
                </div>
                """, unsafe_allow_html=True)
            
            with col_link2:
                st.markdown(f"""
                <div class="link-box">
                    <strong>📰 LinkedIn Feed</strong><br>
                    <a href="{get_linkedin_feed_url()}" target="_blank">Open Feed</a>
                </div>
                """, unsafe_allow_html=True)
            
            with col_link3:
                st.markdown("""
                <div class="link-box">
                    <strong>📊 My Posts</strong><br>
                    <a href="https://www.linkedin.com/in/me/recent-activity/all/" target="_blank">View Activity</a>
                </div>
                """, unsafe_allow_html=True)
            
            if st.session_state.post_history:
                st.markdown("---")
                st.markdown("#### 📝 Posts Created This Session")
                
                for post in reversed(st.session_state.post_history[-5:]):
                    icon = "📝" if post['type'] == 'text' else "📷" if post['type'] == 'image' else "🎬"
                    post_url = post.get('url', '#')
                    st.markdown(f"""
                    <div class="post-history-item">
                        <strong>{icon} {post['time']}</strong> 
                        <a href="{post_url}" target="_blank" style="float: right;">👁️ View on LinkedIn</a>
                        <br>
                        <small>{post['text']}</small>
                    </div>
                    """, unsafe_allow_html=True)
        else:
            st.info("👆 Click 'Refresh Profile' to load your profile")

with tab4:
    st.markdown('<h2 class="section-header">🤖 AI Chat</h2>', unsafe_allow_html=True)
    
    if not st.session_state.agent:
        st.warning("⚠️ Initialize AI first (use sidebar)")
    else:
        st.info("💬 Chat with AI for content ideas!")
        
        for message in st.session_state.messages:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])
        
        if prompt := st.chat_input("Ask anything..."):
            st.session_state.messages.append({"role": "user", "content": prompt})
            with st.chat_message("user"):
                st.markdown(prompt)
            with st.chat_message("assistant"):
                with st.spinner("💭"):
                    try:
                        response = generate_with_retry(st.session_state.agent, prompt)
                        if response:
                            st.markdown(response)
                            st.session_state.messages.append({"role": "assistant", "content": response})
                    except Exception as e:
                        st.error(f"Error: {str(e)}")
        
        if st.button("🗑️ Clear Chat"):
            st.session_state.messages = []
            st.rerun()

st.markdown("---")
st.markdown("""
<div style="text-align: center; padding: 2rem; background: linear-gradient(135deg, #0077B5 0%, #00A0DC 100%); border-radius: 15px; color: white;">
    <h3>🚀 LinkedIn AI Automation</h3>
    <p>Powered by <strong>Groq</strong> • <strong>CAMEL-AI</strong> • <strong>LinkedIn API</strong></p>
</div>
""", unsafe_allow_html=True)