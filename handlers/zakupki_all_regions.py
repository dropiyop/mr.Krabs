import asyncio

import procession
from pydantic_core.core_schema import none_schema
import re
from aiog import *
import init_clients
import json
import datetime
import editabs
import aiohttp
from simple_tg_md import convert_to_md2
from pathlib import Path

def load_keywords(filepath: str =r"keywords_all_regions") -> list[str]:
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
    if matches_keywords(item.get("titleName", ""), keywords):
        return True
    if matches_keywords(item.get("name", ""), keywords):
        return True
    for lot in item.get("lotItems", []):
        if matches_keywords(lot.get("name", ""), keywords):
            return True
    return False






def current_time_ms() -> int:
    """Возвращает текущее время в миллисекундах"""
    today = datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    return int(today.timestamp() * 1000)


async def get_page_items(keyword, page, fz_key, session, headers, base_params, url):
    """Получает элементы с одной страницы"""
    params = base_params.copy()
    params[fz_key] = "on"
    params["pageNumber"] = page
    params["searchString"] = keyword

    await asyncio.sleep(0.6)

    try:
        # Правильное использование aiohttp
        async with session.get(url, headers=headers, params=params, timeout=10) as response:
            # В aiohttp используется response.status, а не response.status_code
            if response.status != 200:
                print(f"HTTP ошибка {response.status}")
                return None, False

            # В aiohttp нужно await для получения текста
            text = await response.text()
            data = json.loads(text)
            return data.get("data", {}).get("list", []), True

    except aiohttp.ClientError as e:
        print(f"[{fz_key}] Сетевая ошибка при keyword='{keyword}': {e}")
        return None, False
    except json.JSONDecodeError as e:
        print(f"[{fz_key}] Ошибка JSON при keyword='{keyword}': {e}")
        # В aiohttp нет r.text, нужно сохранить text выше
        return None, False
    except Exception as e:
        print(f"[{fz_key}] Неизвестная ошибка при keyword='{keyword}': {e}")
        return None, False

async def fetch_pages(keyword, fz_key, session, headers, base_params, url):
    """Генератор страниц"""
    page = 1
    while True:
        page_items, success = await get_page_items(keyword, page, fz_key, session, headers, base_params, url)

        if not success or not page_items:
            return

        yield page_items
        page += 1


async def get_all_today_items_filter(fz_key: str, fz_name: str, session, headers, base_params, url):
    """Версия с генератором"""
    keywords = load_keywords()
    today_start = current_time_ms()
    found_ids = set()
    all_items = []


    for keyword in keywords:
        async for page_items in fetch_pages (keyword, fz_key, session, headers, base_params, url):
            should_break_keyword = False
            for item in page_items:
                created = item.get("createDate") or item.get("updateDate")

                if not created or created <= today_start:
                    created_date = "Unknown" if not created else datetime.datetime.fromtimestamp(created / 1000)
                    should_break_keyword = True
                    break

                number = item.get("number") or item.get("recordId")
                if not number:
                    print("❌ Номер не найден, пропускаем")
                    continue

                # фильтрация по содержанию
                if not is_relevant(item, keywords):
                    continue

                if  editabs.check(str(number), fz_key):
                    continue

                if number:
                    editabs.save(fz=fz_key, number=str(number))
                    print(f"✅ Закупка {number} сохранена в БД")

                uid = f"{fz_key}:{item.get('number') or item.get('recordId')}"
                if uid not in found_ids:

                    response = await init_clients.client_openai.chat.completions.create(
                        model="gpt-4o-mini",
                        messages=[
                            {"role": "system", "content":f"{prompt}"},

                            {"role": "user", "content": f"{item}\n{keywords} "}

                             ],


                    temperature = 0.2
                        )

                    answer_gpt = response.choices[0].message.content.strip()
                    if answer_gpt.lower() == 'нет':
                        print(f"⛔ Закупка {number} отклонена GPT")
                        continue
                    else:
                        found_ids.add(uid)
                        print(found_ids)
                        all_items.append(item)
                        print(f"Добавлен элемент: {uid}")
                        await send_notice(fz_key,fz_name,item)
                else:
                    print(f"Элемент уже найден: {uid}")

            if should_break_keyword:
                break

    found_ids.clear()

    return all_items

async def send_notice(fz_key,fz_name,item):
    users_data = editabs.get_client_users()
    print(f"[{datetime.datetime.now()}] Начинаем проверку для {len(users_data)} пользователей")

    number = item.get("number") or item.get("recordId")

    if not number:
        print("❌ Номер не найден")
        return



    messages_sent = 0
    for user_data in users_data:
        if shutdown_event.is_set():
            break

        chat_id = user_data[0] if isinstance(user_data, tuple) else none_schema()
        print(f"Обрабатываем chat_id: {chat_id}")

        # Ограничиваем количество сообщений для избежания flood control

        max_messages_per_batch = 5  # Максимум сообщений за раз

        number = item.get("number") or item.get("recordId")
        title = item.get("titleName", "").strip()
        method_type = item.get("methodType")
        url_path = item.get("card223Url")

        # Определяем URL
        if url_path:
            full_url = "https://zakupki.gov.ru" + url_path
        elif method_type == "EA20":
            full_url = f"https://zakupki.gov.ru/epz/order/notice/ea20/view/common-info.html?regNumber={number}"
        elif method_type == "EA44":
            full_url = f"https://zakupki.gov.ru/epz/order/notice/ea44/view/common-info.html?regNumber={number}"
        else:
            print(f"Не удалось определить URL для {number} (тип: {method_type})")
            continue

        markup = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="Открыть закупку", url=full_url)]]
            )
        header = "Все регионы\n\n🆕Новая закупка с сайта 'ЕИС закупки'\n\n"
        text = procession.clean_telegram_message(f"{fz_name}\n{title}")
        text = convert_to_md2(text)
        try:
            await init_clients.bot.send_message(
                chat_id=chat_id,
                text=header+text,
                reply_markup=markup,
                parse_mode=aiogram.enums.ParseMode.MARKDOWN_V2
                )


            messages_sent += 1

            # Задержка между сообщениями для избежания flood control
            await asyncio.sleep(1)  # 1 секунда между сообщениями

            # Если отправили много сообщений - делаем большую паузу
            if messages_sent >= max_messages_per_batch:
                print(f"Отправлено {messages_sent} сообщений, делаем паузу...")
                await asyncio.sleep(10)
                messages_sent = 0

        except aiogram.exceptions.TelegramRetryAfter as e:
            print(f"Flood control: нужно подождать {e.retry_after} секунд")
            await asyncio.sleep(e.retry_after + 1)
        except Exception as e:
            print(f"Ошибка при отправке сообщения в чат {chat_id}: {e}")

async def process_items(fz_key, fz_name, session):
    """process_items который использует переданную сессию"""
    url = "https://zakupki.gov.ru/api/mobile/proxy/917/epz/order/extendedsearch/results.html"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Accept-Language": "ru,en;q=0.9",
        "Referer": "https://zakupki.gov.ru/",
        "X-Requested-With": "XMLHttpRequest",
        }
    base_params = {
        "morphology": "on",
        "sortBy": "PUBLISH_DATE",
        "sortDirection": "false",
        "af":"on",
        "currencyId": "-1",
        }

    try:

        await get_all_today_items_filter(
            fz_key, fz_name, session, headers, base_params, url
            )

    except Exception as e:
        print(f"Ошибка в process_items_with_session: {e}")

shutdown_event = asyncio.Event()

async def periodic_check_all_regions():
    interval = 300.0  # 5 минут
    while not shutdown_event.is_set():
        start_time = asyncio.get_event_loop().time()
        session = None

        try:
            # Создаем одну сессию для всей проверки
            session = aiohttp.ClientSession()
            print(f"\n[{datetime.datetime.now()}] Начинаем проверку zakupki_allregions")

            # Обрабатываем с передачей сессии
            await process_items("fz44", "44-ФЗ",  session)
            await process_items("fz223", "223-ФЗ", session)

            # Небольшая задержка между пользователями
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



