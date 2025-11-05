# noinspection PyUnusedLocal,PyMethodMayBeStatic,PyShadowingBuiltins,PyPep8Naming
class DialogProgress(object):
    def create(self, heading, line1=None, line2=None, line3=None):
        """Create and show a progress dialog.

        heading: string or unicode - dialog heading.
        line1: string or unicode - line #1 text.
        line2: string or unicode - line #2 text.
        line3: string or unicode - line #3 text.

        Note:
            Use update() to update lines and progressbar.

        Example:
            pDialog = xbmcgui.DialogProgress()
            ret = pDialog.create('XBMC', 'Initializing script...')
        """
        pass

    def update(self, percent, line1=None, line2=None, line3=None):
        """Update's the progress dialog.

        percent: integer - percent complete. (0:100)
        line1: string or unicode - line #1 text.
        line2: string or unicode - line #2 text.
        line3: string or unicode - line #3 text.

        Note:
            If percent == 0, the progressbar will be hidden.

        Example:
            pDialog.update(25, 'Importing modules...')
        """
        pass

    def iscanceled(self):
        """Returns True if the user pressed cancel."""
        return False

    def close(self):
        """Close the progress dialog."""
        pass


# noinspection PyUnusedLocal,PyMethodMayBeStatic,PyShadowingBuiltins,PyPep8Naming
class DialogProgressBG(object):
    """
    DialogProgressBG class
    Displays a small progress dialog in the corner of the screen.
    """

    def close(self):
        """
        close() --Close the background progress dialog

        example:
        - pDialog.close()
        """
        pass

    def create(self, heading, message=''):
        """
        create(heading[, message])--Create and show a background progress dialog.n

        heading : string or unicode - dialog headingn
        message : [opt] string or unicode - message textn

        *Note, 'heading' is used for the dialog's id. Use a unique heading.n
        Useupdate() to update heading, message and progressbar.n

        example:
        - pDialog = xbmcgui.DialogProgressBG()
        - pDialog.create('Movie Trailers', 'Downloading Monsters Inc. ...')
        """
        pass

    def isFinished(self):
        """
        isFinished() --Returns True if the background dialog is active.

        example:
        - if (pDialog.isFinished()): break
        """
        return False

    def update(self, percent, heading=None, message=None):
        """
        update([percent, heading, message])--Updates the background progress dialog.

        percent : [opt] integer - percent complete. (0:100)
        heading : [opt] string or unicode - dialog heading
        message : [opt] string or unicode - message text

        *Note, To clear heading or message, you must pass a blank character.

        example:
        - pDialog.update(25, message='Downloading Finding Nemo ...')
        """
        pass
