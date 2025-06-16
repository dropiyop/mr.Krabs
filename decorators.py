from aiog import *

def approve_required(handler):
    async def wrapper(message: aiogram.types.Message, *args, **kwargs):
        message_text = None
        if 'event_update' in kwargs and kwargs['event_update'] is not None:
            event_update = kwargs['event_update']

            if event_update.message is not None:
                message_text = event_update.message.text

        if 'text' in kwargs and kwargs['text'] is not None:
            message_text = kwargs['text']

        text = message_text
        state = None
        for el in args:
            if isinstance(el, aiogram.fsm.context.FSMContext):
                state = el

        if 'state' in kwargs and kwargs['state'] is not None:
            state = kwargs['state']

        #Добавить реальную проверку, при которой пользователь может использовать бота
        if True:
            return await handler(message, state, text)

    return wrapper
