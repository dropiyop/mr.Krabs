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

from main import logger


def load_keywords(filepath: str = r"keywords") -> list[str]:
    with open(filepath, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]


def load_prompt(filename: str = "../prompt.txt") -> list[str]:
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

    # Проверяем описание
    if matches_keywords(item.get("description", ""), keywords):
        return True

    # Проверяем предмет закупки
    if matches_keywords(item.get("subject", ""), keywords):
        return True

    return False


def current_time_ms() -> int:
    """Возвращает текущее время в миллисекундах (начало дня)"""
    today = datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    return int(today.timestamp() * 1000)



async def get_page_items(keyword, session, headers, base_payload, url):
    """Получение данных для конкретного keyword"""
    await asyncio.sleep(0.6)

    try:
        # ✅ Добавляем keyword в searchText
        payload = base_payload.copy()
        payload["searchText"] = keyword


        async with session.post(url, headers=headers, json=payload, timeout=15) as response:
            if response.status != 200:
                logger.info(f"HTTP ошибка {response.status} для keyword: {keyword}")
                return None, False

            data = await response.json()
            items = []

            if isinstance(data, dict):
                if "data" in data:
                    items = data["data"].get("items", []) or data["data"].get("list", [])
                elif "items" in data:
                    items = data["items"]
                elif "result" in data:
                    items = data["result"]
                else:
                    if isinstance(data, list):
                        items = data
                    else:
                        return [], True

            return items, True

    except aiohttp.ClientError as e:
        logger.error(f"Сетевая ошибка для keyword '{keyword}': {e}")
        return None, False
    except json.JSONDecodeError as e:
        logger.error(f"Ошибка JSON для keyword '{keyword}': {e}")
        return None, False
    except Exception as e:
        logger.error(f"Неизвестная ошибка для keyword '{keyword}': {e}")
        return None, False


async def get_all_today_items_filter(session, headers, base_payload, url):
    """Получение данных с циклом по keywords через searchText"""
    keywords = load_keywords(filepath="keywords")
    today_start = current_time_ms()

    # ✅ Глобальные множества для дедупликации
    processed_ids = set()  # ID всех обработанных элементов в этом запуске
    found_ids = set()  # ID элементов, прошедших все фильтры
    all_items = []



    for keyword in keywords:
        try:
            await asyncio.sleep(1.5)  # Задержка между запросами

            #  Получаем данные для конкретного keyword
            result = await get_page_items(keyword, session, headers, base_payload, url)

            # Обработка результата
            if result is None:
                logger.error(f"Не удалось получить данные для keyword: {keyword}")
                continue

            if isinstance(result, tuple):
                page_items, success = result
                if not success or page_items is None:
                    logger.error(f"Ошибка получения данных для keyword: {keyword}")
                    continue
            else:
                page_items = result
                if page_items is None:
                    continue

            if not page_items:
                continue


            # Обрабатываем все полученные элементы
            for item in page_items:
                try:
                    item_id = item.get("id")
                    if not item_id:
                        continue

                    # ✅ ПЕРВАЯ проверка: уже обработан в этом запуске?
                    if item_id in processed_ids:
                        continue

                    # Добавляем в обработанные сразу
                    processed_ids.add(item_id)

                    # ✅ ВТОРАЯ проверка: есть ли в БД?
                    if editabs.check(str(item_id)):
                        continue

                    # ✅ ТРЕТЬЯ проверка: релевантность (дополнительная проверка)
                    if not is_relevant(item, keywords):
                        continue

                    created = None
                    try:
                        for date_field in ["publishDate"]:
                            if date_field in item and item[date_field]:
                                created = item[date_field]
                                break

                        # Конвертируем дату если нужно
                        if isinstance(created, str):
                            for fmt in ["%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"]:
                                try:
                                    dt = datetime.datetime.strptime(created[:19], fmt)
                                    created = int(dt.timestamp() * 1000)
                                    break
                                except ValueError:
                                    continue

                    except (IndexError, TypeError, AttributeError) as e:
                        logger.error(f"⚠️ Ошибка обработки даты для {item_id}: {e}")
                        created = None

                    # Фильтруем по дате (только сегодняшние)
                    if created and created < today_start:
                        continue

                    # Сохраняем в БД
                    try:
                        editabs.save(number=str(item_id))
                    except Exception as e:
                        logger.error(f"Ошибка сохранения в БД для {item_id}: {e}")
                        continue

                    # ✅ Проверяем уникальность для отправки
                    uid = f"tender_api:{item_id}"
                    if uid not in found_ids:
                        # GPT проверка
                        try:
                            response = await init_clients.client_openai.chat.completions.create(
                                model="gpt-4o-mini",
                                messages=[
                                    {"role": "system", "content": f"{prompt}"},
                                    {"role": "user", "content": f"{item}\n{keywords}"}
                                    ],
                                temperature=0.2
                                )

                            answer_gpt = response.choices[0].message.content.strip()

                            if answer_gpt.lower() == 'нет':
                                logger.info(f"Закупка {item_id} отклонена GPT")
                                continue
                            else:
                                found_ids.add(uid)
                                all_items.append(item)
                                await send_notice(item)

                        except Exception as e:
                            logger.error(f"Ошибка при обращении к GPT для {item_id}: {e}")


                            # Отправляем уведомление
                            try:
                                await send_notice(item)
                            except Exception as e:
                                logger.error(f"Ошибка отправки уведомления для {item_id}: {e}")



                except Exception as e:
                    logger.error(f"Ошибка обработки элемента {item.get('id', 'NO_ID')}: {e}")
                    import traceback
                    traceback.print_exc()
                    continue

        except Exception as e:
            logger.error(f"Критическая ошибка для keyword '{keyword}': {e}")
            import traceback
            traceback.print_exc()
            continue


    return all_items

async def send_notice(item):
    """Отправка уведомления пользователям"""
    try:
        users_data = editabs.get_client_users()
        logger.info(f"[{datetime.datetime.now()}] Начинаем проверку для {len(users_data)} пользователей")

        # Получаем ID для формирования ссылки
        item_id = item.get("id")
        if not item_id:
            return


        # Получаем название
        title = ""

        lot_name = item.get("subject")
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
                    await asyncio.sleep(10)
                    messages_sent = 0

            except aiogram.exceptions.TelegramRetryAfter as e:
                await asyncio.sleep(e.retry_after + 1)
            except Exception as e:
                logger.error(f"Ошибка при отправке сообщения в чат {chat_id}: {e}")

    except Exception as e:
        logger.error(f"Ошибка в send_notice: {e}")


async def process_tender_api(session):
    """Обработка tender-cache-api"""
    url = "https://tender-cache-api.agregatoreat.ru/api/TradeLot/list-published-trade-lots"

    # Получаем актуальный User-Agent

    headers = {
        "Content-Type": "application/json; charset=UTF-8",
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://agregatoreat.ru",
        "Referer": "https://agregatoreat.ru/",
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        }

    # Базовые параметры запроса
    base_payload = {
        "page": 1,
        "size": 100,
        "lotStates": [2],
        "isEatOnly": True,
        "sort": [{"fieldName": "publishDate", "direction": 2}],
        "searchText": "",  # ✅ Добавлен параметр searchText
        "organizerRegions": ["40"]
        }


    try:
        await get_all_today_items_filter(session, headers, base_payload, url)
    except Exception as e:
        logger.error(f"Ошибка в process_tender_api: {e}")
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
            logger.info(f"\n[{datetime.datetime.now()}] Начинаем проверку ЕАТ")
            await process_tender_api(session)

            # Небольшая задержка
            await asyncio.sleep(0.5)

        except asyncio.CancelledError:
            logger.error("Периодическая проверка отменена")
            break
        except Exception as e:
            logger.error(f"Ошибка в periodic_check: {e}")
            import traceback
            traceback.print_exc()
        finally:
            # ВАЖНО: Всегда закрываем сессию
            if session:
                await session.close()

        # Вычисляем время ожидания
        elapsed = asyncio.get_event_loop().time() - start_time
        sleep_time = max(0.0, interval - elapsed)

        logger.info(f"[{datetime.datetime.now()}] Проверка eat заняла  {elapsed:.2f} сек")

        # Ждем с возможностью прерывания
        try:
            await asyncio.wait_for(
                shutdown_event.wait(),
                timeout=sleep_time
                )
            break
        except asyncio.TimeoutError:
            # Продолжаем цикл
            continue



