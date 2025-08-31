# -*- coding: utf-8 -*-

import sys
import json
import webbrowser
import urllib.parse
import requests
import base64
import os
import subprocess
import platform
import time
import threading
import http.server
import socketserver
from datetime import datetime, timedelta
from urllib.parse import urlparse, parse_qs

class SpotifyPlugin:
    def __init__(self):
        self.client_id = "Enter Your Client ID"
        self.client_secret = "Enter Your Client Secret"
        self.redirect_uri = "http://localhost:8080/callback"
        self.base_url = "https://api.spotify.com/v1"

        # OAuth tokens
        self.access_token = None
        self.refresh_token = None
        self.token_expires = None
        self.search_token = None  # For search (client credentials)

        # Load saved tokens
        self.load_tokens()

        # Define known commands
        self.known_commands = [
            "play", "pause", "next", "previous", "track", "artist", "album",
            "shuffle", "repeat", "volume", "device", "like", "unlike",
            "queue", "reconnect", "mute", "last", "auth"
        ]

    def get_token_file_path(self):
        """Get path for storing tokens"""
        plugin_dir = os.path.dirname(os.path.abspath(__file__))
        return os.path.join(plugin_dir, "spotify_tokens.json")

    def save_tokens(self):
        """Save OAuth tokens to file"""
        try:
            token_data = {
                "access_token": self.access_token,
                "refresh_token": self.refresh_token,
                "token_expires": self.token_expires.isoformat() if self.token_expires else None
            }
            with open(self.get_token_file_path(), 'w') as f:
                json.dump(token_data, f)
        except:
            pass

    def load_tokens(self):
        """Load OAuth tokens from file"""
        try:
            token_file = self.get_token_file_path()
            if os.path.exists(token_file):
                with open(token_file, 'r') as f:
                    token_data = json.load(f)
                self.access_token = token_data.get("access_token")
                self.refresh_token = token_data.get("refresh_token")
                expires_str = token_data.get("token_expires")
                if expires_str:
                    self.token_expires = datetime.fromisoformat(expires_str)
        except:
            pass

    def get_auth_url(self):
        """Generate OAuth authorization URL"""
        scopes = [
            "user-modify-playback-state",
            "user-read-playback-state",
            "user-read-currently-playing",
            "user-read-private"
        ]

        params = {
            "client_id": self.client_id,
            "response_type": "code",
            "redirect_uri": self.redirect_uri,
            "scope": " ".join(scopes),
            "state": "spotify_plugin"
        }

        query_string = "&".join([f"{k}={urllib.parse.quote(str(v))}" for k, v in params.items()])
        return f"https://accounts.spotify.com/authorize?{query_string}"

    def start_auth_server(self):
        """Start local server for OAuth callback"""
        class AuthHandler(http.server.BaseHTTPRequestHandler):
            def __init__(self, plugin_instance):
                self.plugin = plugin_instance
                super().__init__()

            def __call__(self, *args, **kwargs):
                self.plugin = self.plugin
                super().__init__(*args, **kwargs)

            def do_GET(self):
                parsed_url = urlparse(self.path)
                if parsed_url.path == "/callback":
                    query_params = parse_qs(parsed_url.query)

                    if "code" in query_params:
                        auth_code = query_params["code"][0]
                        success = self.plugin.exchange_code_for_token(auth_code)

                        if success:
                            self.send_response(200)
                            self.send_header('Content-type', 'text/html')
                            self.end_headers()
                            self.wfile.write(b"<h1>Success!</h1><p>You can close this window.</p>")
                        else:
                            self.send_response(400)
                            self.send_header('Content-type', 'text/html')
                            self.end_headers()
                            self.wfile.write(b"<h1>Error!</h1><p>Failed to authorize.</p>")
                    else:
                        self.send_response(400)
                        self.send_header('Content-type', 'text/html')
                        self.end_headers()
                        self.wfile.write(b"<h1>Error!</h1><p>No authorization code received.</p>")

                self.plugin.server_should_stop = True

            def log_message(self, format, *args):
                pass  # Suppress logs

        try:
            handler = lambda *args, **kwargs: AuthHandler(self)(*args, **kwargs)
            with socketserver.TCPServer(("", 8080), handler) as httpd:
                self.server_should_stop = False
                while not self.server_should_stop:
                    httpd.handle_request()
        except:
            pass

    def exchange_code_for_token(self, auth_code):
        """Exchange authorization code for access token"""
        auth_header = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()

        headers = {
            "Authorization": f"Basic {auth_header}",
            "Content-Type": "application/x-www-form-urlencoded"
        }

        data = {
            "grant_type": "authorization_code",
            "code": auth_code,
            "redirect_uri": self.redirect_uri
        }

        try:
            response = requests.post("https://accounts.spotify.com/api/token", headers=headers, data=data)
            if response.status_code == 200:
                token_data = response.json()
                self.access_token = token_data.get("access_token")
                self.refresh_token = token_data.get("refresh_token")
                expires_in = token_data.get("expires_in", 3600)
                self.token_expires = datetime.now() + timedelta(seconds=expires_in)
                self.save_tokens()
                return True
        except:
            pass

        return False

    def refresh_access_token(self):
        """Refresh expired access token"""
        if not self.refresh_token:
            return False

        auth_header = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()

        headers = {
            "Authorization": f"Basic {auth_header}",
            "Content-Type": "application/x-www-form-urlencoded"
        }

        data = {
            "grant_type": "refresh_token",
            "refresh_token": self.refresh_token
        }

        try:
            response = requests.post("https://accounts.spotify.com/api/token", headers=headers, data=data)
            if response.status_code == 200:
                token_data = response.json()
                self.access_token = token_data.get("access_token")
                if "refresh_token" in token_data:
                    self.refresh_token = token_data.get("refresh_token")
                expires_in = token_data.get("expires_in", 3600)
                self.token_expires = datetime.now() + timedelta(seconds=expires_in)
                self.save_tokens()
                return True
        except:
            pass

        return False

    def get_valid_access_token(self):
        """Get valid access token, refreshing if needed"""
        if not self.access_token:
            return None

        # Check if token is expired
        if self.token_expires and datetime.now() >= self.token_expires:
            if not self.refresh_access_token():
                return None

        return self.access_token

    def get_search_token(self):
        """Get client credentials token for search"""
        if self.search_token:
            return self.search_token

        auth_url = "https://accounts.spotify.com/api/token"
        auth_header = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()

        headers = {
            "Authorization": f"Basic {auth_header}",
            "Content-Type": "application/x-www-form-urlencoded"
        }

        data = {"grant_type": "client_credentials"}

        try:
            response = requests.post(auth_url, headers=headers, data=data, timeout=5)
            if response.status_code == 200:
                token_data = response.json()
                self.search_token = token_data.get("access_token")
                return self.search_token
        except:
            pass

        return None

    def get_available_devices(self):
        """Get user's available Spotify devices"""
        access_token = self.get_valid_access_token()
        if not access_token:
            return []

        headers = {"Authorization": f"Bearer {access_token}"}

        try:
            response = requests.get(f"{self.base_url}/me/player/devices", headers=headers)
            if response.status_code == 200:
                data = response.json()
                return data.get("devices", [])
        except:
            pass

        return []

    def start_playback(self, track_uri, device_id=None):
        """Start playback of specific track - THIS IS THE KEY METHOD"""
        access_token = self.get_valid_access_token()
        if not access_token:
            return False

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }

        # Prepare playback data
        data = {
            "uris": [track_uri],
            "position_ms": 0
        }

        # Add device if specified
        params = {}
        if device_id:
            params["device_id"] = device_id

        try:
            response = requests.put(f"{self.base_url}/me/player/play",
                                  headers=headers, json=data, params=params)
            return response.status_code in (204, 202)
        except:
            return False

    def get_consistent_image_url(self, images):
        """Select the best image size for consistent display"""
        if not images:
            return "spotify_premium_icon.png"

        sorted_images = sorted(images, key=lambda img: img.get('width', 0), reverse=True)

        for image in sorted_images:
            width = image.get('width', 0)
            if width >= 250 and width <= 350:
                return image.get('url', 'spotify_premium_icon.png')

        for image in sorted_images:
            width = image.get('width', 0)
            if width >= 500:
                return image.get('url', 'spotify_premium_icon.png')

        if sorted_images:
            return sorted_images[0].get('url', 'spotify_premium_icon.png')

        return "spotify_premium_icon.png"

    def is_spotify_running(self):
        try:
            if platform.system() == 'Windows':
                tasks = subprocess.check_output('tasklist', shell=True).decode()
                return 'Spotify.exe' in tasks
            elif platform.system() == 'Darwin':
                result = subprocess.run(['pgrep', '-x', 'Spotify'], capture_output=True)
                return result.returncode == 0
            else:
                result = subprocess.run(['pidof', 'spotify'], capture_output=True)
                return result.returncode == 0
        except:
            return False

    def launch_spotify(self):
        if self.is_spotify_running():
            return True

        try:
            if platform.system() == 'Windows':
                paths = [
                    os.path.join(os.environ.get('APPDATA', ''), 'Spotify', 'Spotify.exe'),
                    os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Microsoft', 'WindowsApps', 'SpotifyAB.SpotifyMusic_zpdnekdrzrea0', 'Spotify.exe'),

                    r'C:\Program Files\Spotify\Spotify.exe',
                    r'C:\Program Files (x86)\Spotify\Spotify.exe'
                ]

                for path in paths:
                    if os.path.exists(path):
                        subprocess.Popen([path])
                        time.sleep(3)
                        return True

                subprocess.Popen(['start', 'spotify:'], shell=True)
                time.sleep(3)
                return True

            elif platform.system() == 'Darwin':
                subprocess.Popen(['open', '-a', 'Spotify'])
                time.sleep(3)
                return True
            else:
                subprocess.Popen(['spotify'])
                time.sleep(3)
                return True
        except:
            return False

    def send_media_key(self, action):
        """Send media key commands"""
        try:
            if platform.system() == 'Windows':
                if action == "play" or action == "pause":
                    subprocess.run(['powershell', '-Command',
                                  '(New-Object -com wscript.shell).SendKeys([char]179)'],
                                 shell=True, check=False)
                elif action == "next":
                    subprocess.run(['powershell', '-Command',
                                  '(New-Object -com wscript.shell).SendKeys([char]176)'],
                                 shell=True, check=False)
                elif action == "previous":
                    subprocess.run(['powershell', '-Command',
                                  '(New-Object -com wscript.shell).SendKeys([char]177)'],
                                 shell=True, check=False)
        except:
            pass

    def show_controls(self):
        """Return list of Spotify commands"""
        is_authenticated = bool(self.get_valid_access_token())

        commands = [
            {"emoji": "🔐", "command": "auth", "description": "Authorize with Spotify (required for playback control)"},

            {"emoji": "▶️", "command": "play", "description": "Resume playback"},
            {"emoji": "⏸️", "command": "pause", "description": "Pause playback"},
            {"emoji": "⏭️", "command": "next", "description": "Skip to next track"},
            {"emoji": "⏮️", "command": "previous", "description": "Go to previous track"},
            {"emoji": "🔀", "command": "shuffle", "description": "Toggle shuffle mode"},
            {"emoji": "🔁", "command": "repeat", "description": "Cycle repeat mode"},
            {"emoji": "🔊", "command": "volume", "description": "Set volume (usage: sp volume 50)"},
            {"emoji": "🔇", "command": "mute", "description": "Toggle mute"},
            {"emoji": "📱", "command": "device", "description": "Show available devices"},
            {"emoji": "❤️", "command": "like", "description": "Like current song"},
            {"emoji": "💔", "command": "unlike", "description": "Remove current song from liked"},
            {"emoji": "➕", "command": "queue", "description": "Add track to queue"},
            {"emoji": "🔄", "command": "reconnect", "description": "Reconnect to Spotify API"},
            {"emoji": "🎵", "command": "track", "description": "Search tracks (usage: sp track [name])"},
            {"emoji": "🎤", "command": "artist", "description": "Search artists (usage: sp artist [name])"},

            {"emoji": "💿", "command": "album", "description": "Search albums (usage: sp album [name])"}
        ]

        results = []
        for cmd in commands:
            title = f"{cmd['emoji']} sp {cmd['command']}"
            if cmd['command'] == 'auth':
                if is_authenticated:
                    title += " ✅"
                else:
                    title += " ❌"

            results.append({
                "Title": title,
                "SubTitle": cmd['description'],
                "IcoPath": "spotify_premium_icon.png",
                "JsonRPCAction": {
                    "method": "execute_command",
                    "parameters": [cmd['command']]
                }
            })

        return results

    def search_tracks(self, query, limit=10):
        """Search for tracks on Spotify with consistent large cover art"""
        token = self.get_search_token()
        if not token:
            return []

        headers = {"Authorization": f"Bearer {token}"}
        params = {"q": query, "type": "track", "limit": limit}

        try:
            response = requests.get(f"{self.base_url}/search", headers=headers, params=params, timeout=5)
            if response.status_code == 200:
                data = response.json()
                tracks = data.get("tracks", {}).get("items", [])

                results = []
                for track in tracks:
                    artist_names = ", ".join([artist["name"] for artist in track["artists"]])
                    duration_ms = track.get("duration_ms", 0)
                    duration_min = duration_ms // 60000
                    duration_sec = (duration_ms % 60000) // 1000

                    album_images = track.get("album", {}).get("images", [])
                    icon_path = self.get_consistent_image_url(album_images)

                    results.append({
                        "Title": f"🎵 {track['name']}",
                        "SubTitle": f"by {artist_names} • {duration_min}:{duration_sec:02d} • {track['album']['name']}",

                        "IcoPath": icon_path,
                        "JsonRPCAction": {
                            "method": "play_track",
                            "parameters": [track["uri"]]  # Use URI instead of external URL
                        }
                    })
                return results
        except:
            pass

        return []

    def search_artists(self, query, limit=8):
        """Search for artists on Spotify with consistent large images"""
        token = self.get_search_token()
        if not token:
            return []

        headers = {"Authorization": f"Bearer {token}"}
        params = {"q": query, "type": "artist", "limit": limit}

        try:
            response = requests.get(f"{self.base_url}/search", headers=headers, params=params, timeout=5)
            if response.status_code == 200:
                data = response.json()
                artists = data.get("artists", {}).get("items", [])

                results = []
                for artist in artists:
                    followers = artist.get("followers", {}).get("total", 0)
                    followers_text = f"{followers:,} followers" if followers > 0 else "Artist"

                    artist_images = artist.get("images", [])
                    icon_path = self.get_consistent_image_url(artist_images)

                    results.append({
                        "Title": f"🎤 {artist['name']}",
                        "SubTitle": f"{followers_text} • {', '.join(artist.get('genres', ['Unknown'])[:2])}",

                        "IcoPath": icon_path,
                        "JsonRPCAction": {
                            "method": "play_artist",
                            "parameters": [artist["uri"]]
                        }
                    })
                return results
        except:
            pass

        return []

    def search_albums(self, query, limit=8):
        """Search for albums on Spotify with consistent large cover art"""
        token = self.get_search_token()
        if not token:
            return []

        headers = {"Authorization": f"Bearer {token}"}
        params = {"q": query, "type": "album", "limit": limit}

        try:
            response = requests.get(f"{self.base_url}/search", headers=headers, params=params, timeout=5)
            if response.status_code == 200:
                data = response.json()
                albums = data.get("albums", {}).get("items", [])

                results = []
                for album in albums:
                    artist_names = ", ".join([artist["name"] for artist in album["artists"]])
                    release_year = album.get("release_date", "")[:4] if album.get("release_date") else ""

                    album_images = album.get("images", [])
                    icon_path = self.get_consistent_image_url(album_images)

                    results.append({
                        "Title": f"💿 {album['name']}",
                        "SubTitle": f"by {artist_names} • {release_year} • {album.get('total_tracks', 0)} tracks",

                        "IcoPath": icon_path,
                        "JsonRPCAction": {
                            "method": "play_album",
                            "parameters": [album["uri"]]
                        }
                    })
                return results
        except:
            pass

        return []

    def query(self, query_str):
        """Main query handler"""
        if isinstance(query_str, list):
            query_str = ' '.join(str(x) for x in query_str)
        elif query_str is None:
            query_str = ""
        else:
            query_str = str(query_str).strip()

        parts = query_str.split() if query_str else []
        if not parts:
            spotify_status = "🟢 Running" if self.is_spotify_running() else "🔴 Not Running"
            auth_status = "🔐 Authorized" if self.get_valid_access_token() else "❌ Not Authorized"

            results = [
                {
                    "Title": f"🎵 Spotify Controls ({spotify_status}, {auth_status})",
                    "SubTitle": "Click to see all available commands",
                    "IcoPath": "spotify_premium_icon.png",
                    "JsonRPCAction": {
                        "method": "show_controls",
                        "parameters": []
                    }
                },
                {
                    "Title": "🔐 Authorize Spotify",
                    "SubTitle": "Required for playback control - click to authenticate",
                    "IcoPath": "spotify_premium_icon.png",
                    "JsonRPCAction": {
                        "method": "execute_command",
                        "parameters": ["auth"]
                    }
                }
            ]
            return results

        first_word = parts[0].lower()
        args = " ".join(parts[1:]) if len(parts) > 1 else ""

        if first_word in self.known_commands:
            command = first_word

            if command == "auth":
                return [{
                    "Title": "🔐 Authorize Spotify",
                    "SubTitle": "Click to start OAuth authorization process",
                    "IcoPath": "spotify_premium_icon.png",
                    "JsonRPCAction": {
                        "method": "authorize_spotify",
                        "parameters": []
                    }
                }]

            elif command in ["play", "pause", "next", "previous", "last"]:
                return [{
                    "Title": f"🎮 {command.title()} Track",
                    "SubTitle": f"Execute {command} command in Spotify app",
                    "IcoPath": "spotify_premium_icon.png",
                    "JsonRPCAction": {
                        "method": "execute_command",
                        "parameters": [command]
                    }
                }]

            elif command == "track":
                if args:
                    return self.search_tracks(args)
                else:
                    return [{
                        "Title": "🎵 Track Search",
                        "SubTitle": "Usage: sp track [track name]",
                        "IcoPath": "spotify_premium_icon.png"
                    }]

            elif command == "artist":
                if args:
                    return self.search_artists(args)
                else:
                    return [{
                        "Title": "🎤 Artist Search",
                        "SubTitle": "Usage: sp artist [artist name]",
                        "IcoPath": "spotify_premium_icon.png"
                    }]

            elif command == "album":
                if args:
                    return self.search_albums(args)
                else:
                    return [{
                        "Title": "💿 Album Search",
                        "SubTitle": "Usage: sp album [album name]",
                        "IcoPath": "spotify_premium_icon.png"
                    }]

            else:
                command_descriptions = {
                    "shuffle": "🔀 Toggle shuffle mode",
                    "repeat": "🔁 Cycle repeat mode",
                    "mute": "🔇 Toggle mute",
                    "device": "📱 Show available devices",
                    "like": "❤️ Like current song",
                    "unlike": "💔 Remove current song from liked",
                    "queue": "➕ Add track to queue",
                    "reconnect": "🔄 Reconnect to Spotify API"
                }

                description = command_descriptions.get(command, f"Execute {command}")
                return [{
                    "Title": description,
                    "SubTitle": f"Execute {command} command",
                    "IcoPath": "spotify_premium_icon.png",
                    "JsonRPCAction": {
                        "method": "execute_command",
                        "parameters": [command]
                    }
                }]

        else:
            # General search
            all_results = []
            track_results = self.search_tracks(query_str, 5)
            all_results.extend(track_results)
            artist_results = self.search_artists(query_str, 3)
            all_results.extend(artist_results)
            album_results = self.search_albums(query_str, 3)
            all_results.extend(album_results)

            if all_results:
                return all_results
            else:
                return [{
                    "Title": f"🔍 No results found for '{query_str}'",
                    "SubTitle": "Try different keywords or use specific commands",
                    "IcoPath": "spotify_premium_icon.png"
                }]

    def execute_command(self, command, value=None):
        """Execute command and return confirmation"""
        if command == "auth":
            return self.authorize_spotify()

        self.launch_spotify()

        success_messages = {
            'play': '▶️ Resuming playback',
            'pause': '⏸️ Pausing playback',
            'next': '⏭️ Skipping to next track',
            'previous': '⏮️ Going to previous track',
            'last': '⏮️ Going to previous track',
            'shuffle': '🔀 Toggling shuffle mode',
            'repeat': '🔁 Cycling repeat mode',
            'volume': f'🔊 Setting volume to {value}' if value else '🔊 Volume control',
            'mute': '🔇 Toggling mute',
            'device': '📱 Opening device selection',
            'like': '❤️ Liking current track',
            'unlike': '💔 Removing from liked songs',
            'queue': '➕ Queue functionality',
            'reconnect': '🔄 Reconnecting to Spotify'
        }

        # Execute the actual command
        if command in ['play', 'pause', 'next', 'previous', 'last']:
            self.send_media_key(command)
        elif command == 'shuffle':
            try:
                subprocess.run(['powershell', '-Command',
                              '(New-Object -com wscript.shell).SendKeys("^s")'],
                             shell=True, check=False)
            except:
                pass
        elif command == 'repeat':
            try:
                subprocess.run(['powershell', '-Command',
                              '(New-Object -com wscript.shell).SendKeys("^r")'],
                             shell=True, check=False)
            except:
                pass

        message = success_messages.get(command, f'Executing {command}')
        return [{
            "Title": "✅ Command Executed",
            "SubTitle": message,
            "IcoPath": "spotify_premium_icon.png"
        }]

    def authorize_spotify(self):
        """Start OAuth authorization process"""
        try:
            auth_url = self.get_auth_url()
            webbrowser.open(auth_url)

            # Start server in a separate thread
            server_thread = threading.Thread(target=self.start_auth_server)
            server_thread.daemon = True
            server_thread.start()

            return [{
                "Title": "🔐 Authorization Started",
                "SubTitle": "Please complete authorization in your browser",
                "IcoPath": "spotify_premium_icon.png"
            }]
        except Exception as e:
            return [{
                "Title": "❌ Authorization Failed",
                "SubTitle": f"Error: {str(e)}",
                "IcoPath": "spotify_premium_icon.png"
            }]

    def play_track(self, track_uri):
        """Play specific track using Spotify Web API"""
        # Ensure Spotify is running
        self.launch_spotify()

        # Try to use Web API for immediate playback
        access_token = self.get_valid_access_token()
        if access_token:
            devices = self.get_available_devices()
            active_device = None

            # Find active device or use first available
            for device in devices:
                if device.get("is_active"):
                    active_device = device.get("id")
                    break

            if not active_device and devices:
                active_device = devices[0].get("id")

            # Try to start playback via API
            if self.start_playback(track_uri, active_device):
                return  # Success - track is now playing

        # Fallback: Open URI in Spotify app
        try:
            if platform.system() == 'Windows':
                subprocess.Popen(['start', track_uri], shell=True)
            elif platform.system() == 'Darwin':
                subprocess.Popen(['open', track_uri])
            else:
                subprocess.Popen(['xdg-open', track_uri])
        except:
            webbrowser.open(f"https://open.spotify.com/{track_uri.replace(':', '/').replace('spotify/', '')}")


    def play_artist(self, artist_uri):
        """Play artist using Web API or fallback"""
        self.play_track(artist_uri)

    def play_album(self, album_uri):
        """Play album using Web API or fallback"""
        self.play_track(album_uri)

    def launch_spotify_app(self):
        """Launch Spotify and return confirmation"""
        success = self.launch_spotify()
        if success:
            return [{
                "Title": "✅ Spotify Launched",
                "SubTitle": "Spotify desktop app is now running",
                "IcoPath": "spotify_premium_icon.png"
            }]
        else:
            return [{
                "Title": "❌ Launch Failed",
                "SubTitle": "Could not launch Spotify desktop app",
                "IcoPath": "spotify_premium_icon.png"
            }]

def main():
    """Main entry point"""
    plugin = SpotifyPlugin()

    try:
        if len(sys.argv) > 1:
            request = json.loads(sys.argv[1])
            method = request.get("method", "")
            parameters = request.get("parameters", [])

            if method == "query":
                query_param = parameters if parameters else ""
                results = plugin.query(query_param)
                print(json.dumps({"result": results}))

            elif method == "show_controls":
                controls_results = plugin.show_controls()
                print(json.dumps({"result": controls_results}))
                return

            elif method == "execute_command":
                command = parameters if parameters else ""
                value = parameters[11] if len(parameters) > 1 else None
                command_results = plugin.execute_command(command, value)
                print(json.dumps({"result": command_results}))
                return

            elif method == "authorize_spotify":
                auth_results = plugin.authorize_spotify()
                print(json.dumps({"result": auth_results}))
                return

            elif method == "launch_spotify_app":
                launch_results = plugin.launch_spotify_app()
                print(json.dumps({"result": launch_results}))
                return

            elif hasattr(plugin, method):
                method_func = getattr(plugin, method)
                if parameters:
                    method_func(*parameters)
                else:
                    method_func()
        else:
            results = plugin.query("")
            print(json.dumps({"result": results}))

    except Exception as e:
        error_result = [{
            "Title": "Spotify Plugin Error",
            "SubTitle": f"Error: {str(e)}",
            "IcoPath": "spotify_premium_icon.png"
        }]
        print(json.dumps({"result": error_result}))

if __name__ == "__main__":
    main()
