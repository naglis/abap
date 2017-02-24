import abc


class AbapCommand(object):

    @abc.abstractmethod
    def get_parser(self, parser):
        '''Adds arguments to the parser'''

    @abc.abstractmethod
    def take_action(self, args) -> None:
        '''Command logic'''
