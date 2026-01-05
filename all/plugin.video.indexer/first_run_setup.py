"""
First Run Setup Wizard for Kodi Plugin
Handles initial setup and GitHub archive download
"""
import os
import json
import xbmc
import xbmcvfs
import xbmcgui
from contextlib import closing


class FirstRunSetup:
    """Handle first-time setup wizard"""
    
    def __init__(self, addon_profile_dir):
        """
        Initialize setup wizard
        
        Args:
            addon_profile_dir: Path to addon's userdata directory
        """
        self.addon_profile_dir = addon_profile_dir
        self.profiles_file = os.path.join(addon_profile_dir, 'profiles.json')
    
    def is_first_run(self):
        """
        Check if this is the first run
        
        Returns:
            True if profiles.json doesn't exist or is empty
        """
        if not xbmcvfs.exists(self.profiles_file):
            xbmc.log("[First Run] profiles.json does not exist - first run detected", xbmc.LOGINFO)
            return True
        
        # Check if file is empty or has no profiles
        try:
            with closing(xbmcvfs.File(self.profiles_file, 'r')) as f:
                content = f.read()
                if not content or content.strip() == '':
                    xbmc.log("[First Run] profiles.json is empty - first run detected", xbmc.LOGINFO)
                    return True
                
                profiles = json.loads(content)
                if not isinstance(profiles, list) or len(profiles) == 0:
                    xbmc.log("[First Run] No profiles found - first run detected", xbmc.LOGINFO)
                    return True
                
            return False
        except Exception as e:
            xbmc.log(f"[First Run] Error reading profiles.json: {e} - treating as first run", xbmc.LOGWARNING)
            return True
    
    def show_setup_wizard(self):
        """
        Display setup wizard dialog
        
        Returns:
            'download' - User wants to download from GitHub
            'skip' - User wants to configure manually
            'cancel' - User cancelled
        """
        dialog = xbmcgui.Dialog()
        
        # Show welcome message
        message = (
            "Welcome to Video Indexer!\n\n"
            "This appears to be your first time using the plugin.\n\n"
            "You can download pre-configured server profiles and metadata cache from GitHub, "
            "or configure everything manually.\n\n"
            "What would you like to do?"
        )
        
        options = [
            "Download setup from GitHub (Recommended)",
            "Configure manually",
            "Cancel"
        ]
        
        choice = dialog.select("First Run Setup", options)
        
        if choice == 0:
            xbmc.log("[First Run] User chose to download from GitHub", xbmc.LOGINFO)
            return 'download'
        elif choice == 1:
            xbmc.log("[First Run] User chose manual configuration", xbmc.LOGINFO)
            return 'skip'
        else:
            xbmc.log("[First Run] User cancelled setup", xbmc.LOGINFO)
            return 'cancel'
    
    def show_download_options(self):
        """
        Show options for what to download
        
        Returns:
            tuple (download_profiles, download_cache)
        """
        dialog = xbmcgui.Dialog()
        
        message = "What would you like to download?"
        
        options = [
            "Both profiles and cache (Recommended)",
            "Only profiles",
            "Only cache",
            "Cancel"
        ]
        
        choice = dialog.select("Download Options", options)
        
        if choice == 0:
            return (True, True)
        elif choice == 1:
            return (True, False)
        elif choice == 2:
            return (False, True)
        else:
            return (False, False)
    
    def run_setup(self):
        """
        Run the complete setup wizard
        
        Returns:
            True if setup completed successfully, False otherwise
        """
        # Check if first run
        if not self.is_first_run():
            xbmc.log("[First Run] Not first run, skipping setup", xbmc.LOGDEBUG)
            return True
        
        # Show wizard
        choice = self.show_setup_wizard()
        
        if choice == 'cancel':
            return False
        elif choice == 'skip':
            # Create empty profiles.json so we don't show wizard again
            try:
                with closing(xbmcvfs.File(self.profiles_file, 'w')) as f:
                    f.write(json.dumps([]))
                xbmc.log("[First Run] Created empty profiles.json for manual configuration", xbmc.LOGINFO)
            except Exception as e:
                xbmc.log(f"[First Run] Failed to create profiles.json: {e}", xbmc.LOGERROR)
            return True
        elif choice == 'download':
            # Show download options
            download_profiles, download_cache = self.show_download_options()
            
            if not download_profiles and not download_cache:
                # User cancelled
                return False
            
            # Download files
            from github_downloader import GitHubDownloader
            downloader = GitHubDownloader(self.addon_profile_dir)
            
            success = downloader.download_all(download_profiles, download_cache)
            
            if success:
                xbmcgui.Dialog().notification(
                    'Setup Complete',
                    'Successfully downloaded and extracted setup files!',
                    xbmcgui.NOTIFICATION_INFO,
                    5000
                )
                xbmc.log("[First Run] Setup completed successfully", xbmc.LOGINFO)
            else:
                xbmcgui.Dialog().ok(
                    'Setup Failed',
                    'Could not download setup files from GitHub.\n'
                    'Please check your internet connection and try again,\n'
                    'or configure manually.'
                )
                xbmc.log("[First Run] Setup failed", xbmc.LOGERROR)
            
            return success
        
        return False
