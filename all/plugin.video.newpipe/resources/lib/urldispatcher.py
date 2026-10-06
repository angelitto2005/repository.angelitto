# -*- coding: utf-8 -*-

'''
    URL dispatcher
    Author Twilight0

    SPDX-License-Identifier: GPL-3.0-only
    See LICENSES/GPL-3.0-only for more information.
'''

import xbmc
import inspect


class URLDispatcher:
    """
    Based on tknorris URLDispatcher which works with 'actions'
    Updated to support class methods.
    """

    def __init__(self):
        self.func_registry = {}
        self.args_registry = {}
        self.kwargs_registry = {}

    def register(self, action, args=None, kwargs=None):

        """
        Decorator function to register a function as a plugin:// url endpoint

        action: the action value passed in the plugin:// url
        args: a list  of strings that are the positional arguments to expect
        kwargs: a list of strings that are the keyword arguments to expect

        * Positional argument must be in the order the function expect
        * kwargs can be in any order
        * kwargs without positional arguments are supported by passing in a kwargs but no args
        * If there are no arguments at all, just "action" can be specified
        """

        if args is None:
            args = []
        if kwargs is None:
            kwargs = []

        def decorator(f):
            if action in self.func_registry:
                message = 'Error: {0} already registered as {1}'.format(str(f), action)
                raise Exception(message)

            self.func_registry[action.strip()] = f
            self.args_registry[action] = args
            self.kwargs_registry[action] = kwargs
            return f

        return decorator

    def dispatch(self, action, queries, instance=None):
        """
        Dispatch function to execute function registered for the provided action.

        instance: Optional class instance to use if the action is a class method.
        """
        if action not in self.func_registry:
            message = 'Error: Attempt to invoke unregistered action |{0}|'.format(action)
            raise Exception(message)

        func = self.func_registry[action]
        args = []
        kwargs = {}
        unused_args = queries.copy()

        # Handle positional arguments
        if self.args_registry[action]:
            for arg in self.args_registry[action]:
                arg = arg.strip()
                if arg in queries:
                    args.append(self.__coerce(queries[arg]))
                    del unused_args[arg]
                else:
                    message = 'Error: action |{0}| requested argument |{1}| but it was not provided.'.format(action,
                                                                                                             arg)
                    raise Exception(message)

        # Handle keyword arguments
        if self.kwargs_registry[action]:
            for arg in self.kwargs_registry[action]:
                arg = arg.strip()
                if arg in queries:
                    kwargs[arg] = self.__coerce(queries[arg])
                    del unused_args[arg]

        if 'action' in unused_args:
            del unused_args['action']

        # Logic for calling methods vs functions
        if instance and not inspect.ismethod(func):
            # If an instance is provided and the function isn't already bound,
            # we call it as an instance method.
            func(instance, *args, **kwargs)
        else:
            # Otherwise, call it as a standalone function or bound method
            func(*args, **kwargs)

    def showactions(self):
        for action in self.func_registry:
            value = self.func_registry[action]
            args = self.args_registry[action]
            kwargs = self.kwargs_registry[action]
            line = 'Action {0} Registered - {1} args: {2} kwargs: {3}'.format(
                str(action), str(value), str(args), str(kwargs)
            )
            xbmc.log(line, xbmc.LOGDEBUG)

    # since all params are passed as strings, do any conversions necessary to get good types (e.g. boolean)
    @staticmethod
    def __coerce(arg):
        try:
            temp = arg.lower()
            if temp == 'true':
                return True
            elif temp == 'false':
                return False
            elif temp == 'none':
                return None
            return arg
        except:
            return arg


urldispatcher = URLDispatcher()
__all__ = ['urldispatcher']
