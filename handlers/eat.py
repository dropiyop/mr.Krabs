import asyncio
import aiohttp
import json
import datetime
from playwright.async_api import async_playwright
import editabs
import init_clients
import procession
from simple_tg_md import convert_to_md2
from aiogram import types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import aiogram.exceptions
import aiogram.enums
from pathlib import Path

def load_keywords(filepath: str = r"keywords") -> list[str]:
    with open(filepath, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]


def load_prompt(filename: str = "prompt.txt") -> list[str]:
    # Получаем путь к корню проекта
    current_file = Path(__file__)
    project_root = current_file.parent.parent  # handlers/../
    filepath = project_root / filename

    if not filepath.exists():
        raise FileNotFoundError(f"Файл {filepath} не найден")

    with open(filepath, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]

prompt = load_prompt("prompt.txt")

def matches_keywords(text: str, keywords: list[str]) -> bool:
    lowered = text.lower()
    return any(keyword.lower() in lowered for keyword in keywords)


def is_relevant(item: dict, keywords: list[str]) -> bool:
    # Проверяем название закупки
    if matches_keywords(item.get("purchaseName", ""), keywords):
        return True

    # Проверяем описание
    if matches_keywords(item.get("description", ""), keywords):
        return True

    # Проверяем название организации
    if matches_keywords(item.get("organizationName", ""), keywords):
        return True

    # Проверяем предмет закупки
    if matches_keywords(item.get("subject", ""), keywords):
        return True

    return False


def current_time_ms() -> int:
    """Возвращает текущее время в миллисекундах (начало дня)"""
    today = datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    return int(today.timestamp() * 1000)


async def get_current_user_agent():
    """Получаем актуальный User-Agent через Playwright"""
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()

        user_agent = await page.evaluate("navigator.userAgent")
        await browser.close()
        return user_agent


async def get_page_items(keyword,  session, headers, base_payload, url):

    await asyncio.sleep(0.6)

    try:
        async with session.post(url, headers=headers, json=base_payload, timeout=15) as response:
            if response.status != 200:
                print(f"HTTP ошибка {response.status}")
                return None, False

            data = await response.json()
            # Структура ответа может отличаться, проверяем разные варианты
            items = []
            if isinstance(data, dict):
                if "data" in data:
                    items = data["data"].get("items", []) or data["data"].get("list", [])
                elif "items" in data:
                    items = data["items"]
                elif "result" in data:
                    items = data["result"]
                else:
                    # Если структура неизвестна, попробуем сам data как список
                    if isinstance(data, list):
                        items = data
                    else:
                        print(f"Неизвестная структура ответа: {list(data.keys())}")
                        return [], True

            return items

    except aiohttp.ClientError as e:
        print(f"Сетевая ошибка при keyword='{keyword}': {e}")
        return None, False
    except json.JSONDecodeError as e:
        print(f"Ошибка JSON при keyword='{keyword}': {e}")
        return None, False
    except Exception as e:
        print(f"Неизвестная ошибка при keyword='{keyword}': {e}")
        return None, False



async def get_all_today_items_filter(session, headers, base_payload, url):
    """Версия с генератором для tender-cache-api"""
    keywords = load_keywords()
    today_start = current_time_ms()
    found_ids = set()
    all_items = []

    print(f"Начинаем поиск с времени: {today_start}")

    for keyword in keywords:
        await asyncio.sleep(1.5)
        page_items = await get_page_items(keyword, session, headers, base_payload, url)

        print(keyword)

        for item in page_items:
            # Проверяем дату создания/обновления
            created = None
            for date_field in ["publishDate"]:
                if date_field in item and item[date_field]:
                    created = item[date_field]
                    break

            # Если дата в строковом формате, конвертируем
            if isinstance(created, str):
                try:
                    # Пробуем разные форматы даты
                    for fmt in ["%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"]:
                        try:
                            dt = datetime.datetime.strptime(created[:19], fmt)
                            created = int(dt.timestamp() * 1000)
                            break
                        except ValueError:
                            continue
                except (IndexError, TypeError):
                    created = None

            if created and created <= today_start:
                created_date = "Unknown" if not created else datetime.datetime.fromtimestamp(created / 1000)
                break



            # Получаем ID для уникальности (используем ID как основной ключ для БД)
            item_id = item.get("id")
            if not item_id:
                print("❌ ID не найден, пропускаем")
                continue

            # # Фильтрация по содержанию
            # if not is_relevant(item, keywords):
            #     continue

            # Проверяем, есть ли уже в БД (используем ID как уникальный ключ)
            if editabs.check(str(item_id), ):
                continue

            # Сохраняем в БД (используем ID как уникальный ключ)
            editabs.save(number=str(item_id))
            print(f"✅ Закупка {item_id} сохранена в БД")

            uid = f"tender_api:{item_id}"
            if uid not in found_ids:
                # Проверяем через GPT
                try:
                    response = await init_clients.client_openai.chat.completions.create(
                        model="gpt-4o-mini",
                        messages=[
                            {"role": "system", "content":f"{prompt}"},
                            {"role": "user", "content": f"{item}\n{keywords}"}
                            ],
                        temperature=0.2
                        )

                    answer_gpt = response.choices[0].message.content.strip()
                    print(f"Ответ GPT: {answer_gpt[:100]}...")

                    if answer_gpt.lower() == 'нет':
                        print(f"⛔ Закупка {item_id} отклонена GPT")
                        continue
                    else:
                        found_ids.add(uid)
                        all_items.append(item)
                        print(f"✅ Добавлен элемент: {uid}")
                        await send_notice(item)

                except Exception as e:
                    print(f"Ошибка при обращении к GPT: {e}")
                    # Если GPT недоступен, добавляем элемент без проверки
                    found_ids.add(uid)
                    all_items.append(item)
                    await send_notice(item)

            else:
                print(f"Элемент уже найден: {uid}")


    found_ids.clear()
    return all_items


async def send_notice(item):
    """Отправка уведомления пользователям"""
    try:
        users_data = editabs.get_client_users()
        print(f"[{datetime.datetime.now()}] Начинаем проверку для {len(users_data)} пользователей")

        # Получаем ID для формирования ссылки
        item_id = item.get("id")
        if not item_id:
            print("❌ ID не найден")
            return



        # Получаем название
        title = ""
        if "lotItems" in item and isinstance(item["lotItems"], list) and item["lotItems"]:
            lot_name = item["lotItems"][0].get("name")
            if lot_name:
                title = str(lot_name).strip()




        # Формируем URL на основе ID
        full_url = f"https://agregatoreat.ru/purchases/announcement/{item_id}/info"

        messages_sent = 0
        max_messages_per_batch = 5

        for user_data in users_data:
            if shutdown_event.is_set():
                break

            chat_id = user_data[0] if isinstance(user_data, tuple) else user_data
            print(f"Обрабатываем chat_id: {chat_id}")

            markup = InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="Открыть закупку", url=full_url)]]
                )

            # Формируем более информативное сообщение
            header = f"🆕 Новая закупка с сайта EAT'\n\n"
            text = f"📋 {title}"

            # Добавляем информацию об организаторе, если есть
            if "organizerInfo" in item and item["organizerInfo"].get("name"):
                text += f"\n\n🏢 Организатор: {item['organizerInfo']['name']}\n"

            text = convert_to_md2(text)

            try:
                await init_clients.bot.send_message(
                    chat_id=chat_id,
                    text=header+text,
                    reply_markup=markup,
                    parse_mode=aiogram.enums.ParseMode.MARKDOWN_V2
                    )

                messages_sent += 1
                await asyncio.sleep(1)  # Задержка между сообщениями

                if messages_sent >= max_messages_per_batch:
                    print(f"Отправлено {messages_sent} сообщений, делаем паузу...")
                    await asyncio.sleep(10)
                    messages_sent = 0

            except aiogram.exceptions.TelegramRetryAfter as e:
                print(f"Flood control: нужно подождать {e.retry_after} секунд")
                await asyncio.sleep(e.retry_after + 1)
            except Exception as e:
                print(f"Ошибка при отправке сообщения в чат {chat_id}: {e}")

    except Exception as e:
        print(f"Ошибка в send_notice: {e}")


async def process_tender_api(session):
    """Обработка tender-cache-api"""
    url = "https://tender-cache-api.agregatoreat.ru/api/TradeLot/list-published-trade-lots"

    # Получаем актуальный User-Agent
    user_agent = await get_current_user_agent()

    headers = {
        "Content-Type": "application/json; charset=UTF-8",
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://agregatoreat.ru",
        "Referer": "https://agregatoreat.ru/",
        "User-Agent": user_agent
        }

    # Базовые параметры запроса
    base_payload = {

    "page": 1,
    "size": 100,
    "lotStates": [2],
    "isEatOnly": True,
   "sort": [{"fieldName": "publishDate", "direction": 2}],

"organizerRegions": ["40"]

}

    try:
        await get_all_today_items_filter(session, headers, base_payload, url)
    except Exception as e:
        print(f"Ошибка в process_tender_api: {e}")
        import traceback
        traceback.print_exc()


shutdown_event = asyncio.Event()


async def periodic_check_eat():
    """Периодическая проверка новых закупок"""
    interval = 300.0  # 5 минут

    while not shutdown_event.is_set():
        start_time = asyncio.get_event_loop().time()
        session = None

        try:
            # Создаем одну сессию для всей проверки
            connector = aiohttp.TCPConnector(limit=10)
            timeout = aiohttp.ClientTimeout(total=30)
            session = aiohttp.ClientSession(connector=connector, timeout=timeout)
            print(f"\n[{datetime.datetime.now()}] Начинаем проверку ЕАТ")
            await process_tender_api(session)

            # Небольшая задержка
            await asyncio.sleep(0.5)

        except asyncio.CancelledError:
            print("Периодическая проверка отменена")
            break
        except Exception as e:
            print(f"Ошибка в periodic_check: {e}")
            import traceback
            traceback.print_exc()
        finally:
            # ВАЖНО: Всегда закрываем сессию
            if session:
                await session.close()

        # Вычисляем время ожидания
        elapsed = asyncio.get_event_loop().time() - start_time
        sleep_time = max(0.0, interval - elapsed)

        print(f"[{datetime.datetime.now()}] Проверка заняла {elapsed:.2f} сек")

        # Ждем с возможностью прерывания
        try:
            await asyncio.wait_for(
                shutdown_event.wait(),
                timeout=sleep_time
                )
            print("Получен сигнал остановки")
            break
        except asyncio.TimeoutError:
            # Продолжаем цикл
            continue



