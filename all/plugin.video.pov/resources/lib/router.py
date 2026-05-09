import sys
from entry import Router

if __name__ == '__main__':
	with Router() as r: r.routing(sys)

