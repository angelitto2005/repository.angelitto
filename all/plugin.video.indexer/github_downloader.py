"""
GitHub Archive Downloader for Kodi Plugin
Downloads and extracts profiles.zip and cache.zip from GitHub
"""
import os
import json
import xbmc
import xbmcvfs
import xbmcgui
from contextlib import closing

try:
    import requests
except ImportError:
    xbmc.log("[GitHub Downloader] requests module not available", xbmc.LOGERROR)
    requests = None

try:
    import zipfile
except ImportError:
    xbmc.log("[GitHub Downloader] zipfile module not available", xbmc.LOGERROR)
    zipfile = None


class GitHubDownloader:
    """Download and extract archives from GitHub"""
    
    # Default GitHub URLs
    DEFAULT_PROFILES_URL = "https://github.com/staycanuca/indexer/raw/refs/heads/main/profiles.zip"
    DEFAULT_CACHE_URL = "https://github.com/staycanuca/indexer/raw/refs/heads/main/cache.zip"
    
    def __init__(self, addon_profile_dir):
        """
        Initialize downloader
        
        Args:
            addon_profile_dir: Path to addon's userdata directory
        """
        self.addon_profile_dir = addon_profile_dir
        self.temp_dir = os.path.join(addon_profile_dir, 'temp')
        
        # Ensure temp directory exists
        if not xbmcvfs.exists(self.temp_dir):
            xbmcvfs.mkdirs(self.temp_dir)
    
    def download_file(self, url, destination_path, progress_callback=None):
        """
        Download a file from URL with progress tracking
        
        Args:
            url: URL to download from
            destination_path: Where to save the file
            progress_callback: Optional callback(percent, message)
        
        Returns:
            True if successful, False otherwise
        """
        if not requests:
            xbmc.log("[GitHub Downloader] requests module not available", xbmc.LOGERROR)
            return False
        
        try:
            xbmc.log(f"[GitHub Downloader] Downloading from: {url}", xbmc.LOGINFO)
            
            # Start download with streaming
            response = requests.get(url, stream=True, timeout=30)
            response.raise_for_status()
            
            total_size = int(response.headers.get('content-length', 0))
            downloaded = 0
            
            # Write to file
            with closing(xbmcvfs.File(destination_path, 'wb')) as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        
                        if progress_callback and total_size > 0:
                            percent = int((downloaded / total_size) * 100)
                            size_mb = downloaded / (1024 * 1024)
                            total_mb = total_size / (1024 * 1024)
                            progress_callback(percent, f"Downloaded {size_mb:.1f}/{total_mb:.1f} MB")
            
            xbmc.log(f"[GitHub Downloader] Successfully downloaded to: {destination_path}", xbmc.LOGINFO)
            return True
            
        except requests.RequestException as e:
            xbmc.log(f"[GitHub Downloader] Download failed: {e}", xbmc.LOGERROR)
            return False
        except Exception as e:
            xbmc.log(f"[GitHub Downloader] Unexpected error: {e}", xbmc.LOGERROR)
            return False
    
    def extract_zip(self, zip_path, extract_to, progress_callback=None):
        """
        Extract ZIP archive to destination
        
        Args:
            zip_path: Path to ZIP file
            extract_to: Destination directory
            progress_callback: Optional callback(percent, message)
        
        Returns:
            List of extracted files, or None on error
        """
        if not zipfile:
            xbmc.log("[GitHub Downloader] zipfile module not available", xbmc.LOGERROR)
            return None
        
        try:
            # Convert Kodi special paths to absolute paths
            zip_path_absolute = xbmcvfs.translatePath(zip_path)
            extract_to_absolute = xbmcvfs.translatePath(extract_to)
            
            xbmc.log(f"[GitHub Downloader] Extracting {zip_path_absolute} to {extract_to_absolute}", xbmc.LOGINFO)
            
            extracted_files = []
            
            with zipfile.ZipFile(zip_path_absolute, 'r') as zip_ref:
                file_list = [f for f in zip_ref.filelist if not f.is_dir()]
                total_files = len(file_list)
                
                for i, file_info in enumerate(file_list):
                    # Extract file content
                    file_content = zip_ref.read(file_info.filename)
                    
                    # Determine destination path (extract to root of extract_to)
                    filename = os.path.basename(file_info.filename)
                    dest_path = os.path.join(extract_to, filename)
                    
                    # Write using xbmcvfs
                    with closing(xbmcvfs.File(dest_path, 'wb')) as f:
                        f.write(file_content)
                    
                    extracted_files.append(dest_path)
                    
                    if progress_callback:
                        percent = int(((i + 1) / total_files) * 100)
                        progress_callback(percent, f"Extracted {i + 1}/{total_files} files")
                    
                    xbmc.log(f"[GitHub Downloader] Extracted: {filename}", xbmc.LOGDEBUG)
            
            xbmc.log(f"[GitHub Downloader] Successfully extracted {len(extracted_files)} files", xbmc.LOGINFO)
            return extracted_files
            
        except zipfile.BadZipFile as e:
            xbmc.log(f"[GitHub Downloader] Invalid ZIP file: {e}", xbmc.LOGERROR)
            return None
        except Exception as e:
            xbmc.log(f"[GitHub Downloader] Extraction failed: {e}", xbmc.LOGERROR)
            import traceback
            xbmc.log(f"[GitHub Downloader] Traceback: {traceback.format_exc()}", xbmc.LOGERROR)
            return None
    
    def cleanup_temp_files(self):
        """Remove temporary downloaded files"""
        try:
            if xbmcvfs.exists(self.temp_dir):
                # List and delete all files in temp directory
                dirs, files = xbmcvfs.listdir(self.temp_dir)
                for file in files:
                    file_path = os.path.join(self.temp_dir, file)
                    xbmcvfs.delete(file_path)
                xbmc.log("[GitHub Downloader] Cleaned up temporary files", xbmc.LOGDEBUG)
        except Exception as e:
            xbmc.log(f"[GitHub Downloader] Cleanup failed: {e}", xbmc.LOGWARNING)
    
    def download_and_extract_profiles(self, url=None, progress_callback=None):
        """
        Download and extract profiles.zip
        
        Args:
            url: Custom URL (uses default if None)
            progress_callback: Optional callback(percent, message)
        
        Returns:
            True if successful, False otherwise
        """
        url = url or self.DEFAULT_PROFILES_URL
        temp_zip = os.path.join(self.temp_dir, 'profiles.zip')
        
        # Download
        if progress_callback:
            progress_callback(0, "Downloading profiles.zip...")
        
        if not self.download_file(url, temp_zip, progress_callback):
            return False
        
        # Extract
        if progress_callback:
            progress_callback(50, "Extracting profiles.zip...")
        
        extracted = self.extract_zip(temp_zip, self.addon_profile_dir, progress_callback)
        
        # Cleanup
        xbmcvfs.delete(temp_zip)
        
        return extracted is not None
    
    def download_and_extract_cache(self, url=None, progress_callback=None):
        """
        Download and extract cache.zip
        
        Args:
            url: Custom URL (uses default if None)
            progress_callback: Optional callback(percent, message)
        
        Returns:
            True if successful, False otherwise
        """
        url = url or self.DEFAULT_CACHE_URL
        temp_zip = os.path.join(self.temp_dir, 'cache.zip')
        
        # Download
        if progress_callback:
            progress_callback(0, "Downloading cache.zip...")
        
        if not self.download_file(url, temp_zip, progress_callback):
            return False
        
        # Extract
        if progress_callback:
            progress_callback(50, "Extracting cache.zip...")
        
        extracted = self.extract_zip(temp_zip, self.addon_profile_dir, progress_callback)
        
        # Cleanup
        xbmcvfs.delete(temp_zip)
        
        return extracted is not None
    
    def download_all(self, download_profiles=True, download_cache=True):
        """
        Download and extract both archives with progress dialog
        
        Args:
            download_profiles: Whether to download profiles.zip
            download_cache: Whether to download cache.zip
        
        Returns:
            True if all selected downloads succeeded, False otherwise
        """
        dialog = xbmcgui.DialogProgress()
        dialog.create('Downloading Setup Files', 'Preparing...')
        
        success = True
        
        try:
            # Download profiles
            if download_profiles:
                dialog.update(0, 'Downloading profiles.zip...')
                
                def profiles_progress(percent, message):
                    dialog.update(int(percent / 2), message)  # 0-50%
                
                if not self.download_and_extract_profiles(progress_callback=profiles_progress):
                    success = False
                    dialog.close()
                    xbmcgui.Dialog().ok('Download Failed', 'Could not download profiles.zip')
                    return False
            
            # Download cache
            if download_cache:
                start_percent = 50 if download_profiles else 0
                dialog.update(start_percent, 'Downloading cache.zip...')
                
                def cache_progress(percent, message):
                    actual_percent = start_percent + int(percent / 2)
                    dialog.update(actual_percent, message)
                
                if not self.download_and_extract_cache(progress_callback=cache_progress):
                    success = False
                    dialog.close()
                    xbmcgui.Dialog().ok('Download Failed', 'Could not download cache.zip')
                    return False
            
            dialog.update(100, 'Download complete!')
            
        except Exception as e:
            xbmc.log(f"[GitHub Downloader] Download failed: {e}", xbmc.LOGERROR)
            success = False
        finally:
            dialog.close()
            self.cleanup_temp_files()
        
        return success
