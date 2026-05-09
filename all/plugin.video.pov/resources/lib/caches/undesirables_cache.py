from fenom.control import multiselectDialog, notification, yesnoDialog, dialog
from fenom.undesirables import Undesirables


def undesirablesUserRemove():
	undesirables_cache = Undesirables()
	user_undesirables = undesirables_cache.get_user_defined()
	if not user_undesirables: return notification(message='No User Undesirables Set')
	choices = multiselectDialog(user_undesirables, heading='Select to Remove From List')
	if not choices: return
	removals = [(user_undesirables[i],) for i in choices]
	undesirables_cache.remove_many(removals)

def undesirablesUserRemoveAll():
	undesirables_cache = Undesirables()
	user_undesirables = undesirables_cache.get_user_defined()
	if not user_undesirables: return notification(message='No User Undesirables Set')
	if not yesnoDialog('Are you sure?'): return
	removals = [(i,) for i in user_undesirables]
	undesirables_cache.remove_many(removals)
	notification(message='Success')

def undesirablesInput():
	undesirables_cache = Undesirables()
	user_defined = undesirables_cache.get_user_defined()
	if user_defined: current_user_string = ','.join(user_defined)
	else: current_user_string = ''
	undesirables_string = dialog.input(heading='Define Extra Undesirables (Comma Separated)', defaultt=current_user_string)
	if not undesirables_string: return
	new_undesirables = undesirables_string.replace(' ', '').split(',')
	new_settings = [(i, True, True) for i in new_undesirables]
	undesirables_cache.set_many(new_settings)

