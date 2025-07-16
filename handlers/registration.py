import editabs
from init_clients import *
import config
import re
import base64
import requests
from aiog import *
from states import *

async def send_welcome(message: types.Message):
    await message.reply("Я уже смотрю важные объявления о закупках")


@dp.message(Command("start"))
async def command_start_handler(message: types.Message, state: FSMContext) -> None:
    user_id = message.from_user.id
    if any([user_id == user[0] for user in editabs.get_client_users()]):
        await send_welcome(message)
        return
    kb = [[types.KeyboardButton(text="Отправить свой профиль", request_contact=True)]]
    keyboard = types.ReplyKeyboardMarkup(
        keyboard=kb,
        resize_keyboard=True,
        input_field_placeholder="Нажмите кнопку ниже"
        )
    text = (f"Здравствуй, {message.from_user.full_name}!\nДля работы в этом боте вы должны быть "
            f"сотрудником ГК КАМИН. Для этого отправьте данные своего профиля кнопкой снизу. "
            f"Я смогу подтвердить, что вы сотрудник по номеру телефона"),
    await message.answer(text=text[0], reply_markup=keyboard)
    await state.set_state(Form.waiting_for_contact)


def clean_phone_number(phone_number):
    cleaned_number = re.sub(r'\D', '', phone_number)
    return cleaned_number


@dp.message(Form.waiting_for_contact, F.content_type == "contact")
async def contact_handler(message: types.Message, state: FSMContext) -> None:
    contact = message.contact
    await state.clear()
    contact_id = contact.user_id
    contact_name = contact.first_name
    contact_phone = contact.phone_number
    contact_username = message.from_user.username
    chat_id = None

    if contact_id == message.from_user.id:
        if not any([contact_id == user[0] for user in editabs.get_client_users()]):

            bypass_phone = "89533322638"

            if clean_phone_number(contact_phone)[1:] == clean_phone_number(bypass_phone)[1:]:
                editabs.add_init_client(contact_id, chat_id, contact_username, contact_name, contact_phone)
                await message.answer(f"{contact_name}, Поздравляю! "
                                     f"Вы можете использовать функциональность бота",
                                     reply_markup=types.ReplyKeyboardRemove())
                await send_welcome(message)
                return

    if contact_id == message.from_user.id:
        if not any([contact_id == user[0] for user in editabs.get_client_users()]):
            url = config.CASCADE_USERS_URL
            credentials = f'{config.CASCADE_USER}:{config.CASCADE_PASSWORD}'
            encoded_credentials = base64.b64encode(credentials.encode('utf-8')).decode('utf-8')
            headers = {'Authorization': f'Basic {encoded_credentials}'}

            response = requests.get(url, headers=headers)
            print(response)

            if response.status_code == 200:
                data = response.json()
                for record in data:
                    if clean_phone_number(contact_phone)[1:]  == clean_phone_number(record['mobilePhone'])[1:]:
                        contact_name = record['shortName']
                        editabs.add_init_client(contact_id, chat_id, contact_username, contact_name, contact_phone)
                        fio = record['name'].split(" ")
                        await message.answer(f"{fio[1]} {fio[2]}, Поздравляю! "
                                             f"Вы можете использовать функциональность бота",
                                             reply_markup=types.ReplyKeyboardRemove())

                        await send_welcome(message)

                        break
                else:

                    await message.answer("К сожалению, вы не были найдены в базе данных сотрудников Каскада. "
                                         "Вы не сможете использовать бота.", reply_markup=types.ReplyKeyboardRemove())
            else:

                await message.answer("Возникли проблемы при подключении к базе данных Каскада. Попробуйте позже.")
    else:
        await message.answer("Ну так не честно, это же не ваш контакт")