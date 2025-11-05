import sys, os

current = os.path.dirname(__file__)

sys.path.insert(0, os.path.normpath(os.path.join(current, '..')))
from .service import main

if not os.path.exists('temp'):
	os.mkdir('temp')

main()
