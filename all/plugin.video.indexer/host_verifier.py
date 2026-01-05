"""
Host Verifier Module
Checks connectivity to FTP and HTTP servers
"""
import socket
import requests
from ftplib import FTP
import xbmc

def check_http_host(host, port=80, timeout=5, verify=True):
    """
    Check if HTTP host is reachable
    
    Args:
        host: Hostname or IP address
        port: Port number (default 80)
        timeout: Timeout in seconds
        verify: Verify SSL certificates (default True)
        
    Returns:
        bool: True if host is reachable, False otherwise
    """
    try:
        # Try to parse URL if full URL is provided
        if host.startswith('http://') or host.startswith('https://'):
            url = host
        else:
            url = f"http://{host}"
            if port != 80:
                url = f"http://{host}:{port}"
                
        # Disable warnings if verification disabled
        if not verify:
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        
        # Try HEAD request first (faster)
        response = requests.head(url, timeout=timeout, allow_redirects=True, verify=verify)
        return True
    except requests.RequestException:
        # If HEAD fails, try GET
        try:
            response = requests.get(url, timeout=timeout, allow_redirects=True, stream=True, verify=verify)
            return True
        except requests.RequestException:
            pass
    except Exception as e:
        xbmc.log(f"[Host Verifier] HTTP check failed for {host}: {e}", xbmc.LOGDEBUG)
    
    return False


def check_ftp_host(host, port=21, user=None, password=None, timeout=5):
    """
    Check if FTP host is reachable
    """
    try:
        # Set socket timeout
        socket.setdefaulttimeout(timeout)
        
        ftp = FTP()
        ftp.connect(host, port, timeout=timeout)
        
        # Login
        if user and password:
            ftp.login(user, password)
        else:
            ftp.login()  # Anonymous login
        
        # If we got here, connection successful
        ftp.quit()
        return True
        
    except Exception as e:
        xbmc.log(f"[Host Verifier] FTP check failed for {host}: {e}", xbmc.LOGDEBUG)
        return False
    finally:
        # Reset socket timeout
        socket.setdefaulttimeout(None)


def verify_profile(profile, timeout=5):
    """
    Verify if profile's host is reachable
    """
    profile_type = profile.get('type', 'http')
    host = profile.get('host')
    
    if not host:
        xbmc.log(f"[Host Verifier] No host specified for profile {profile.get('id')}", xbmc.LOGWARNING)
        return False
    
    try:
        if profile_type == 'http':
            import xbmcaddon
            addon = xbmcaddon.Addon()
            verify_ssl = addon.getSetting('verify_ssl') == 'true'
            
            # Extract port if specified in host
            port = 80
            if ':' in host and not host.startswith('http'):
                host_parts = host.split(':')
                host = host_parts[0]
                try:
                    port = int(host_parts[1])
                except (ValueError, IndexError):
                    pass
            
            return check_http_host(host, port, timeout, verify_ssl)
            
        elif profile_type == 'ftp':
            # Extract port if specified
            port = 21
            if ':' in host:
                host_parts = host.split(':')
                host = host_parts[0]
                try:
                    port = int(host_parts[1])
                except (ValueError, IndexError):
                    pass
            
            user = profile.get('user')
            password = profile.get('pass')
            anonymous = profile.get('anonymous', False)
            
            if anonymous:
                user = None
                password = None
            
            return check_ftp_host(host, port, user, password, timeout)
        
        else:
            xbmc.log(f"[Host Verifier] Unknown profile type: {profile_type}", xbmc.LOGWARNING)
            return False
            
    except Exception as e:
        xbmc.log(f"[Host Verifier] Error verifying profile {profile.get('id')}: {e}", xbmc.LOGERROR)
        return False


def verify_all_profiles(profiles, timeout=5, progress_callback=None):
    """
    Verify all profiles and return their online status
    
    Args:
        profiles: List of profile dictionaries
        timeout: Timeout in seconds for each check
        progress_callback: Optional callback function(current, total, profile_name)
        
    Returns:
        dict: Mapping of profile_id to online status (True/False)
    """
    results = {}
    total = len(profiles)
    
    for i, profile in enumerate(profiles):
        profile_id = profile.get('id')
        profile_name = profile.get('name', f'Profile {profile_id}')
        
        if progress_callback:
            progress_callback(i + 1, total, profile_name)
        
        xbmc.log(f"[Host Verifier] Checking profile: {profile_name}", xbmc.LOGINFO)
        is_online = verify_profile(profile, timeout)
        results[profile_id] = is_online
        
        status = "ONLINE" if is_online else "OFFLINE"
        xbmc.log(f"[Host Verifier] Profile '{profile_name}' is {status}", xbmc.LOGINFO)
    
    return results
