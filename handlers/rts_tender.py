import re
from datetime import datetime, date
from playwright.sync_api import sync_playwright
import json
import time
import asyncio
from aiog import *
import editabs
import init_clients
from simple_tg_md import convert_to_md2
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import openai
from pathlib import Path
import websockets
import threading


def load_keywords(filepath: str = r"../keywords") -> list[str]:
    with open(filepath, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]


def load_prompt(filename: str = "../prompt.txt") -> list[str]:
    current_file = Path(__file__)
    project_root = current_file.parent.parent
    filepath = project_root / filename

    if not filepath.exists():
        raise FileNotFoundError(f"Файл {filepath} не найден")

    with open(filepath, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]


prompt = load_prompt("prompt.txt")


class RTSWebSocketVerification:
    """Класс для WebSocket верификации через SignalR"""

    def __init__(self, cookies_dict):
        self.cookies_dict = cookies_dict
        self.verification_complete = False
        self.verification_token = None

    def get_cookie_string(self):
        """Преобразует словарь cookies в строку"""
        return '; '.join([f"{k}={v}" for k, v in self.cookies_dict.items()])

    async def verify_async(self, timeout=10):
        """Асинхронная WebSocket верификация"""
        try:
            # Формируем заголовки с дополнительными параметрами из curl
            headers = {
                "Pragma": "no-cache",
                "Origin": "https://www.rts-tender.ru",
                "Accept-Language": "ru,en;q=0.9",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 YaBrowser/24.1.0.0 Safari/537.36",
                "Cache-Control": "no-cache",
                "Cookie": self.get_cookie_string(),
                "Sec-WebSocket-Version": "13",
                "Sec-WebSocket-Extensions": "permessage-deflate; client_max_window_bits"
                }

            print("🔌 Подключаемся к WebSocket (первая верификация)...")

            # ПЕРВАЯ ВЕРИФИКАЦИЯ
            async with websockets.connect(
                    "wss://www.rts-tender.ru/poisk/verification",
                    extra_headers=headers,
                    timeout=timeout,
                    compression="deflate"
                    ) as websocket:
                print("✅ WebSocket соединение установлено (первая верификация)")

                # Отправляем последовательность сообщений для первой верификации
                messages = [
                    '{"protocol":"json","version":1}',
                    '{}',
                    '{"arguments":[],"invocationId":"0","target":"SetToken","type":1}',
                    ]

                for i, msg in enumerate(messages):
                    print(f"📤 Первая верификация - отправляем сообщение {i + 1}: {msg}")
                    await websocket.send(msg)
                    await asyncio.sleep(0.5)

                # Ждем ответы от первой верификации
                try:
                    timeout_counter = 0
                    async for message in websocket:
                        print(f"📨 Первая верификация - WebSocket сообщение: {message}")
                        timeout_counter += 1

                        try:
                            if message.startswith('{"type":3'):
                                data = json.loads(message)
                                if data.get('invocationId') == '0' and 'result' in data:
                                    if data['result']:
                                        first_token = data['result']
                                        print(f"✅ Получен токен первой верификации: {first_token}")
                                        break
                        except json.JSONDecodeError:
                            continue

                        if timeout_counter > 10:  # Защита от бесконечного ожидания
                            break

                except asyncio.TimeoutError:
                    print("⏰ Таймаут первой верификации")

            print("🔌 Начинаем вторую верификацию...")
            await asyncio.sleep(1)  # Пауза между верификациями

            # ВТОРАЯ ВЕРИФИКАЦИЯ
            async with websockets.connect(
                    "wss://www.rts-tender.ru/poisk/verification",
                    extra_headers=headers,
                    timeout=timeout,
                    compression="deflate"
                    ) as websocket:
                print("✅ WebSocket соединение установлено (вторая верификация)")

                # Отправляем последовательность сообщений для второй верификации
                messages = [
                    '{"protocol":"json","version":1}',
                    '{}',
                    '{"arguments":[],"invocationId":"0","target":"SetToken","type":1}',
                    ]

                for i, msg in enumerate(messages):
                    print(f"📤 Вторая верификация - отправляем сообщение {i + 1}: {msg}")
                    await websocket.send(msg)
                    await asyncio.sleep(0.5)

                # Ждем ответы от второй верификации
                try:
                    timeout_counter = 0
                    async for message in websocket:
                        print(f"📨 Вторая верификация - WebSocket сообщение: {message}")
                        timeout_counter += 1

                        try:
                            if message.startswith('{"type":3'):
                                data = json.loads(message)
                                if data.get('invocationId') == '0' and 'result' in data:
                                    if data['result']:
                                        self.verification_token = data['result']
                                        print(f"✅ Получен финальный токен верификации: {self.verification_token}")
                                        return True
                                    else:
                                        print("⚠️ Получен пустой результат второй верификации")
                                        return False
                        except json.JSONDecodeError:
                            continue

                        if timeout_counter > 10:  # Защита от бесконечного ожидания
                            break

                except asyncio.TimeoutError:
                    print("⏰ Таймаут второй верификации")
                    return False

        except Exception as e:
            print(f"❌ Ошибка WebSocket верификации: {e}")
            return False

    def verify(self, timeout=10):
        """Синхронная обертка для WebSocket верификации"""
        try:
            # Создаем новый event loop для синхронного вызова
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                result = loop.run_until_complete(self.verify_async(timeout))
                return result
            finally:
                loop.close()
        except Exception as e:
            print(f"❌ Ошибка синхронной WebSocket верификации: {e}")
            return False


def filter_by_today_date(notices):
    """Фильтрует записи только по сегодняшней дате"""
    today = datetime.now().strftime("%d.%m.%Y")
    today_notices = []

    print(f"🗓️ Фильтруем по сегодняшней дате: {today}")

    for notice in notices:
        pub_date = notice.get('publishDate', notice.get('pub_date', ''))

        if pub_date and isinstance(pub_date, str):
            try:
                if 'T' in pub_date:
                    parsed_date = datetime.fromisoformat(pub_date.replace('Z', '+00:00'))
                    pub_date = parsed_date.strftime("%d.%m.%Y")
            except:
                pass

        if pub_date == today:
            today_notices.append(notice)
        else:
            print(f"⏭️ Пропускаем запись с датой {pub_date}: {notice.get('notificationNumber', 'Unknown')}")

    print(f"📅 Найдено {len(today_notices)} записей за сегодня из {len(notices)} общих")
    return today_notices


async def filter_notices(notices, keywords):
    """Фильтрует уведомления по ключевым словам и исключениям"""
    sent_count = 0
    filtered_notices = []

    for notice in notices:
        search_text = f"{notice.get('subject', '')} {notice.get('customerName', '')} {notice.get('name', '')}"

        number = notice.get('notificationNumber', notice.get('number', ''))
        if not number or number.strip() == '' or number == 'N/A':
            print(f"⚠️ Пропускаем закупку без номера: {notice.get('subject', 'Unknown')}")
            continue

        if editabs.check(number, fz=None):
            print(f"🔁 Закупка {number} уже отправлена ранее")
            continue

        if number:
            editabs.save(number, fz=None)
            print(f"💾 Номер {number} сохранен")

        if not any(keyword.lower() in search_text.lower() for keyword in keywords):
            continue
        else:
            response = await init_clients.client_openai.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": f"{prompt}"},
                    {"role": "user", "content": f"{notice}\n{keywords}"}
                    ],
                temperature=0.2,
                )

            answer_gpt = response.choices[0].message.content.strip()
            print(answer_gpt)
            if answer_gpt.lower() == 'нет':
                print(f"⛔ Закупка {number} отклонена GPT")
                continue

            filtered_notices.append(notice)
            sent_count += 1
            print(f"✅ Закупка {number} прошла фильтр")

    return filtered_notices, sent_count


async def send_notifications(notice):
    """Отправляет одно уведомление в Telegram всем пользователям"""
    users_data = editabs.get_client_users()
    success_count = 0

    for user_data in users_data:
        chat_id = user_data[0] if isinstance(user_data, tuple) else user_data

        if not chat_id:
            continue

        try:
            number = notice.get('notificationNumber', notice.get('number', ''))
            full_url = f"https://www.rts-tender.ru/poisk/Notice/Notice/{number}"

            price = notice.get('maxPrice', notice.get('price', 'N/A'))
            if isinstance(price, (int, float)) and price > 0:
                price_text = f"{price:,.0f} руб.".replace(',', ' ')
            else:
                price_text = 'N/A'

            text = f"""🔔 Новая закупка с РТС-Тендер

📝 *Номер:* {convert_to_md2(number)}
📋 *Наименование:* {convert_to_md2(notice.get('subject', notice.get('name', 'N/A')))}
🏢 *Заказчик:* {convert_to_md2(notice.get('customerName', 'N/A'))}
💰 *Начальная цена:* {convert_to_md2(price_text)}
📅 *Дата публикации:* {convert_to_md2(notice.get('publishDate', notice.get('pub_date', 'N/A')))}
"""

            markup = InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="Открыть закупку", url=full_url)]]
                )

            await init_clients.bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=markup,
                parse_mode=aiogram.enums.ParseMode.MARKDOWN_V2
                )

            success_count += 1
            print(f"✅ Отправлено для chat_id: {chat_id}")
            await asyncio.sleep(0.5)

        except Exception as e:
            print(f"❌ Ошибка при отправке для chat_id {chat_id}: {e}")

    return success_count


async def send_all_filtered_notices(filtered_notices):
    """Отправляет все отфильтрованные уведомления"""
    total_sent = 0

    for notice in filtered_notices:
        number = notice.get('notificationNumber', notice.get('number', 'Unknown'))
        subject = notice.get('subject', notice.get('name', 'Unknown'))
        print(f"📤 Отправляем: {number} - {subject}")
        sent_count = await send_notifications(notice)
        if sent_count > 0:
            total_sent += 1

        await asyncio.sleep(2)

    print(f"🏁 Отправлено {total_sent} закупок из {len(filtered_notices)}")
    return total_sent


def scrape_rts_tender_sync():
    """Синхронная функция для скрапинга RTS-Tender с WebSocket верификацией"""
    notices_data = []
    current_page = 0
    today = date.today()
    today_formatted = today.strftime("%d.%m.%Y")
    should_continue = True
    max_pages = 10

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-blink-features=AutomationControlled']
            )

        context = browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36',
            locale='ru-RU',
            ignore_https_errors=True
            )

        context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined,
            });
        """)

        page = context.new_page()

        page.set_extra_http_headers({
            'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
            'Accept-Encoding': 'gzip, deflate, br, zstd',
            'Cache-Control': 'max-age=0',
            'Sec-CH-UA': '"Not)A;Brand";v="8", "Chromium";v="138", "Google Chrome";v="138"',
            'Sec-CH-UA-Mobile': '?0',
            'Sec-CH-UA-Platform': '"Windows"',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Upgrade-Insecure-Requests': '1'
            })

        def handle_response(response):
            nonlocal notices_data, should_continue
            if "ajaxwithfullmodel" in response.url:
                print(f"📥 Получен ответ API на странице {current_page}: {response.url}")
                try:
                    data = response.json()
                    print(f"📊 Тип данных: {type(data)}")

                    page_notices = []
                    if isinstance(data, dict):
                        if 'items' in data:
                            page_notices = data['items']
                        elif 'data' in data:
                            page_notices = data['data']
                        elif 'notices' in data:
                            page_notices = data['notices']
                        else:
                            print(f"⚠️ Неизвестная структура данных: {list(data.keys())}")
                    elif isinstance(data, list):
                        page_notices = data

                    notices_data.extend(page_notices)
                    print(f"📋 Добавлено {len(page_notices)} записей со страницы {current_page}")

                    today_found = False
                    for notice in page_notices:
                        pub_date = notice.get('publishDate', '')
                        if pub_date:
                            try:
                                if 'T' in pub_date:
                                    parsed_date = datetime.fromisoformat(pub_date.replace('Z', '+00:00'))
                                    date_str = parsed_date.strftime("%d.%m.%Y")
                                    if date_str == today_formatted:
                                        today_found = True
                                        break
                            except:
                                continue

                    if not today_found and len(page_notices) > 0:
                        print("⏹️ На странице нет сегодняшних записей, останавливаемся")
                        should_continue = False

                except Exception as e:
                    print(f"❌ Ошибка парсинга JSON: {e}")

        page.on("response", handle_response)


        try:
            print("🌐 Переходим на страницу поиска RTS-Tender...")
            page.goto('https://www.rts-tender.ru/poisk/search', timeout=30000)
            page.wait_for_timeout(1000)

            # Проходим Anti-DDoS защиту
            print("🔄 Проходим Anti-DDoS защиту...")
            try:
                page.wait_for_function(
                    "document.getElementById('statusText') === null || document.getElementById('statusText').textContent.includes('Обновите страницу')",
                    timeout=15000
                    )

                if page.locator('#statusText').count() > 0:
                    print("⏳ Ждем автоматического перенаправления...")
                    page.wait_for_url('**/poisk/search', timeout=20000)

            except Exception as e:
                print(f"⚠️ Возможная ошибка Anti-DDoS: {e}")
                page.reload(timeout=30000)

            page.wait_for_load_state("networkidle")
            print("✅ Anti-DDoS защита пройдена!")

            # Получаем cookies и токены для WebSocket верификации
            cookies = context.cookies()
            cookies_dict = {cookie['name']: cookie['value'] for cookie in cookies}

            print("🔌 Начинаем WebSocket верификацию В САМОМ НАЧАЛЕ...")
            ws_verification = RTSWebSocketVerification(cookies_dict)

            if ws_verification.verify(timeout=15):
                print("✅ WebSocket верификация успешна!")
                verification_token = ws_verification.verification_token
                if verification_token:
                    print(f"🎫 Получен токен верификации: {verification_token}")
                else:
                    print("⚠️ Токен верификации не получен")
            else:
                print("❌ WebSocket верификация провалилась!")
                return []  # Останавливаем выполнение, если верификация не прошла

            xsrf_token = cookies_dict.get('XSRF-TOKEN')
            if not xsrf_token:
                print("❌ Не удалось получить XSRF токен")
                return []

            print(f"🔐 Получен XSRF токен: {xsrf_token}")



            # Получаем hidden поля
            hidden = {}
            for inp in page.query_selector_all('#hiddenForm input[type="hidden"]'):
                name = inp.get_attribute('name')
                val = inp.get_attribute('value')
                if name == 'AllCount':
                    try:
                        val = int(val)
                    except:
                        pass
                hidden[name] = val

            # Создаем базовый фильтр поиска
            search_filter = {
                "filter": {
                    "contractStatuses": [],
                    "notificationStatuses": [1],
                    "isSearch223": True,
                    "isSearch44": True,
                    "isSearch615": False,
                    "isSearchCOM": False,
                    "isSearchZMO": True,
                    "isSearchSP": False,
                    "isSearchRFP": False,
                    "customerIds": [],
                    "deliveryRegionIds": [],
                    "etpCodes": [],
                    "inn": None,
                    "innConcurents": None,
                    "innOrganizers": None,
                    "nmcIds": [],
                    "number": None,
                    "okeiCodes": [],
                    "okpd2Codes": [],
                    "ktruCodes": [],
                    "preferenseIds": [],
                    "pwsIds": list(range(1, 26)),
                    "regionIds": [],
                    "restrict": [],
                    "stateAtMarketPlace": [],
                    "truName": None,
                    "applicationGuaranteeAmount": None,
                    "auctionTimeEnd": None,
                    "auctionTimeStart": None,
                    "collectingEndDateEnd": None,
                    "collectingEndDateStart": None,
                    "contractGuaranteeAmount": None,
                    "contractSignEnd": None,
                    "contractSignStart": None,
                    "createDateEnd": None,
                    "createDateStart": None,
                    "isExactMatch": False,
                    "isMedicAnalog": False,
                    "isNotJoint": False,
                    "isSearchAttachment": True,
                    "isSearchByOrganization": False,
                    "isSearchNotActualStandarts": False,
                    "isSearchPaymentDate": False,
                    "isSearchPrePayment": False,
                    "isSmp": None,
                    "nmcFrom": 0,
                    "nmcTo": None,
                    "priceFrom": None,
                    "priceTo": None,
                    "publishDateEnd": None,
                    "publishDateStart": None,
                    "quantityFrom": None,
                    "quantityTo": None,
                    "withoutApplicationGuarantee": False,
                    "withoutContractGuarantee": False
                    },
                "isAscendingSorting": False,
                "searchQuery": "",
                "skip": 0,
                "sort": "PublishDate",
                "top": 50,
                "type": 1,
                "RegionAlias": "",
                "CityName": ""
                }

            flt = {k: v for k, v in search_filter['filter'].items() if v is not None}
            flt['isSearch615'] = False
            flt['isSearchCOM'] = False
            flt['isSearchZMO'] = False
            flt['isSearchSP'] = False

            check_payload = {
                "filter": flt,
                "SearchProfileId": hidden["SearchProfileId"],
                "Type": hidden["Type"],
                "AllCount": hidden["AllCount"]
                }

            while should_continue and current_page < max_pages:
                print(f"🔍 Запрашиваем страницу {current_page + 1}...")

                search_filter["skip"] = current_page * search_filter["top"]

                try:
                    response1 = page.request.post(
                        'https://www.rts-tender.ru/poisk/search/ajax/checkqueryforindustry',
                        headers={
                            'Accept': 'application/json, text/plain, */*',
                            'Content-Type': 'application/json',
                            'X-XSRF-Token': xsrf_token,
                            'X-Requested-With': 'XMLHttpRequest'
                            },
                        data=json.dumps(check_payload, ensure_ascii=False)
                        )

                    if response1.status != 200:
                        print(f"❌ Ошибка industry check: {response1.status}")
                        break

                    response2 = page.request.post(
                        'https://www.rts-tender.ru/poisk/search/ajaxwithfullmodel',
                        headers={
                            'Accept': 'application/json, text/plain, */*',
                            'Accept-Language': 'ru,en;q=0.9',
                            'Connection': 'keep-alive',
                            'Content-Type': 'application/json',
                            'FOToken': verification_token if verification_token else '',
                            'Origin': 'https://www.rts-tender.ru',
                            'Referer': 'https://www.rts-tender.ru/poisk/search',
                            'Sec-Fetch-Dest': 'empty',
                            'Sec-Fetch-Mode': 'cors',
                            'Sec-Fetch-Site': 'same-origin',
                            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 YaBrowser/24.1.0.0 Safari/537.36',
                            'X-Requested-With': 'XMLHttpRequest',
                            'X-XSRF-TOKEN': xsrf_token,
                            'sec-ch-ua': '"Not_A Brand";v="8", "Chromium";v="120", "YaBrowser";v="24.1", "Yowser";v="2.5", "YaBrowserCorp";v="120.0"',
                            'sec-ch-ua-mobile': '?0',
                            'sec-ch-ua-platform': '"Windows"'
                            },
                        data=json.dumps(check_payload)
                        )

                    if response2.status != 200:
                        print(f"❌ Ошибка API запроса: {response2.status}")
                        break

                    page.wait_for_timeout(2000)
                    current_page += 1

                except Exception as e:
                    print(f"❌ Ошибка при API запросе: {e}")
                    break

        except Exception as e:
            print(f"❌ Общая ошибка скрапинга: {e}")

        finally:
            browser.close()

    print(f"✅ Итого собрано {len(notices_data)} записей с {current_page} страниц")

    # Фильтруем только сегодняшние записи
    today_notices = []
    today_str = today.strftime("%d.%m.%Y")

    for notice in notices_data:
        pub_date = notice.get('publishDate', '')
        if pub_date:
            try:
                if 'T' in pub_date:
                    parsed_date = datetime.fromisoformat(pub_date.replace('Z', '+00:00'))
                    date_str = parsed_date.strftime("%d.%m.%Y")
                    if date_str == today_str:
                        today_notices.append(notice)
            except:
                continue

    print(f"✅ Найдено {len(today_notices)} записей за сегодня из {len(notices_data)} общих")
    return today_notices


async def periodic_check_rts_tender():
    """Периодическая проверка RTS-Tender"""
    while True:
        try:
            print(f"\n[{datetime.now()}] Начинаем проверку RTS-Tender")

            keywords = load_keywords()

            loop = asyncio.get_event_loop()
            with ThreadPoolExecutor() as executor:
                notices_data = await loop.run_in_executor(executor, scrape_rts_tender_sync)

            if notices_data:
                print(f"Получено {len(notices_data)} закупок")
                today_notices = filter_by_today_date(notices_data)

                if not today_notices:
                    print("📅 Нет закупок за сегодняшнюю дату")
                else:
                    print("🔍 Пример данных за сегодня:")
                    for i, notice in enumerate(today_notices[:2]):
                        print(f"  Запись {i + 1}:")
                        print(f"    number: '{notice.get('notificationNumber', 'MISSING')}'")
                        print(f"    subject: '{notice.get('subject', 'MISSING')}'")

                    filtered_notices, found_count = await filter_notices(notices_data, keywords)
                    print(f"Найдено {found_count} подходящих закупок из {len(notices_data)} общих")

                    if filtered_notices:
                        sent_count = await send_all_filtered_notices(filtered_notices)
                        print(f"✅ RTS-Tender: отправлено {sent_count} уведомлений")
                    else:
                        print("Нет новых закупок для отправки")
            else:
                print("Данные не получены")

        except Exception as e:
            print(f"❌ Ошибка при проверке RTS-Tender: {e}")
            import traceback
            traceback.print_exc()

        print("⏰ Следующая проверка RTS-Tender через 10 минут...")
        await asyncio.sleep(600)


# Для запуска скрипта
if __name__ == "__main__":
    asyncio.run(periodic_check_rts_tender())