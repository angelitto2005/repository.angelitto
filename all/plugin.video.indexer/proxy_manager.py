"""
Proxy Manager Module
Simple proxy rotation for HTTP requests
"""
import logging
import requests
from threading import Lock

class ProxyRotator:
    """
    Simple proxy rotator with sequential rotation
    Supports manual proxy list only
    """
    
    def __init__(self, proxy_list=None):
        """
        Initialize proxy rotator
        
        Args:
            proxy_list: List of proxy strings in format "host:port"
        """
        self.proxies = proxy_list or []
        self.current_index = 0
        self.lock = Lock()
        self.failed_proxies = set()
        
        logging.info(f"[Proxy Rotator] Initialized with {len(self.proxies)} proxies")
    
    def get_next_proxy(self):
        """
        Get next proxy in rotation (sequential)
        
        Returns:
            dict: Proxy dict for requests library or None if no proxies available
        """
        if not self.proxies:
            return None
        
        with self.lock:
            # Find next working proxy
            attempts = 0
            max_attempts = len(self.proxies)
            
            while attempts < max_attempts:
                proxy = self.proxies[self.current_index]
                self.current_index = (self.current_index + 1) % len(self.proxies)
                
                # Skip failed proxies
                if proxy not in self.failed_proxies:
                    proxy_dict = {
                        'http': f'http://{proxy}',
                        'https': f'http://{proxy}'
                    }
                    logging.debug(f"[Proxy Rotator] Using proxy: {proxy}")
                    return proxy_dict
                
                attempts += 1
            
            # All proxies failed
            logging.warning("[Proxy Rotator] All proxies have failed")
            return None
    
    def mark_proxy_failed(self, proxy_dict):
        """
        Mark a proxy as failed
        
        Args:
            proxy_dict: Proxy dict returned by get_next_proxy()
        """
        if not proxy_dict:
            return
        
        # Extract proxy string from dict
        proxy_url = proxy_dict.get('http', '')
        if proxy_url.startswith('http://'):
            proxy = proxy_url[7:]  # Remove 'http://'
            
            with self.lock:
                self.failed_proxies.add(proxy)
                logging.warning(f"[Proxy Rotator] Marked proxy as failed: {proxy}")
                
                # Check if all proxies failed
                if len(self.failed_proxies) >= len(self.proxies):
                    logging.error("[Proxy Rotator] All proxies have been marked as failed")
    
    def reset_failed_proxies(self):
        """Reset the failed proxies set (give them another chance)"""
        with self.lock:
            count = len(self.failed_proxies)
            self.failed_proxies.clear()
            logging.info(f"[Proxy Rotator] Reset {count} failed proxies")
    
    def has_working_proxies(self):
        """
        Check if there are any working proxies available
        
        Returns:
            bool: True if working proxies available
        """
        return len(self.failed_proxies) < len(self.proxies)
    
    def get_stats(self):
        """
        Get proxy statistics
        
        Returns:
            dict: Statistics about proxy usage
        """
        return {
            'total': len(self.proxies),
            'failed': len(self.failed_proxies),
            'working': len(self.proxies) - len(self.failed_proxies)
        }


def create_proxy_session(proxy_list, timeout=30):
    """
    Create a requests session with proxy rotation
    
    Args:
        proxy_list: List of proxy strings
        timeout: Request timeout in seconds
        
    Returns:
        tuple: (session, proxy_rotator)
    """
    session = requests.Session()
    proxy_rotator = ProxyRotator(proxy_list)
    
    # Set initial proxy
    proxy_dict = proxy_rotator.get_next_proxy()
    if proxy_dict:
        session.proxies.update(proxy_dict)
        logging.info(f"[Proxy Session] Created session with proxy rotation")
    else:
        logging.info(f"[Proxy Session] Created session without proxies")
    
    return session, proxy_rotator


def make_request_with_proxy_rotation(session, proxy_rotator, url, max_retries=3, **kwargs):
    """
    Make HTTP request with automatic proxy rotation on failure
    
    Args:
        session: requests.Session object
        proxy_rotator: ProxyRotator instance
        url: URL to request
        max_retries: Maximum number of proxy retries
        **kwargs: Additional arguments for requests.get()
        
    Returns:
        requests.Response or None
    """
    last_error = None
    
    for attempt in range(max_retries + 1):
        try:
            # Make request
            response = session.get(url, **kwargs)
            response.raise_for_status()
            return response
            
        except requests.RequestException as e:
            last_error = e
            logging.warning(f"[Proxy Request] Attempt {attempt + 1} failed: {e}")
            
            # Mark current proxy as failed and rotate to next
            if proxy_rotator and proxy_rotator.has_working_proxies():
                proxy_rotator.mark_proxy_failed(session.proxies)
                next_proxy = proxy_rotator.get_next_proxy()
                
                if next_proxy:
                    session.proxies.update(next_proxy)
                    logging.info(f"[Proxy Request] Rotating to next proxy")
                else:
                    # No more working proxies, try direct connection
                    logging.warning(f"[Proxy Request] No working proxies, trying direct connection")
                    session.proxies.clear()
            else:
                # Already using direct connection or no proxies available
                break
    
    # All attempts failed
    logging.error(f"[Proxy Request] All attempts failed for {url}: {last_error}")
    return None
