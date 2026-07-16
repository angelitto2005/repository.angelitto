from entry import logger, POVMonitor

if __name__ == '__main__':
	logger('POV', 'Main Monitor Service Starting (%s)' % POVMonitor.ver())
	logger('POV', 'Settings Monitor Service Starting')

	POVMonitor().run()

	logger('POV', 'Settings Monitor Service Finished')
	logger('POV', 'Main Monitor Service Finished')

