from datetime import  date
from playwright.async_api import async_playwright
import asyncio
from aiog import *
import re
import editabs
import init_clients
from simple_tg_md import convert_to_md2
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
import os
from main import logger
import platform

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

def filter_by_today_date(notices):
    """Фильтрует записи только по сегодняшней дате"""
    today = datetime.now().strftime("%d.%m.%Y")
    today_notices = []


    for notice in notices:
        pub_date = notice.get('pub_date', '')
        if pub_date == today:
            today_notices.append(notice)


    return today_notices



async def filter_notices(notices, keywords):
    """Фильтрует уведомления по ключевым словам и исключениям и сразу отправляет в ТГ"""
    sent_count = 0
    filtered_notices = []

    for notice in notices:
        # Объединяем текст для поиска
        search_text = f"{notice.get('name', '')} {notice.get('uchr_sname', '')}"

        number = notice.get('number', '')
        if  editabs.check(number, fz=None):
            continue

        if number:
            editabs.save(number, fz=None)

        # Проверка наличия ключевых слов
        if not any(keyword.lower() in search_text.lower() for keyword in keywords):
            continue
        else:
            # GPT-фильтрация
            response = await init_clients.client_openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": f"{prompt}"
                 },
                {"role": "user", "content":  f"{notice}\n{keywords}" }
                ],
                temperature=0.2,
            )

            answer_gpt = response.choices[0].message.content.strip()
            if answer_gpt.lower() == 'нет':
                logger.info(f"Закупка {number} отклонена GPT")
                continue


            filtered_notices.append(notice)
            sent_count += 1

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
            # Формируем ссылку
            full_url = f"https://mimz.admoblkaluga.ru/GzwSP/Notice?noticeLink={notice['link']}"

            # Формируем текст сообщения
            text = f"""🔔 Новая закупка с сайта  МИМЗ
            
            📝Номер:{convert_to_md2(notice.get('number', 'N/A'))}
            📋Наименование: {convert_to_md2(notice.get('name', 'N/A'))}
            """

            # Создаем инлайн клавиатуру
            markup = InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="Открыть закупку", url=full_url)]]
                )

            # Отправляем сообщение
            await init_clients.bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=markup,
                parse_mode=aiogram.enums.ParseMode.MARKDOWN_V2
                )

            success_count += 1

            # Небольшая задержка между пользователями
            await asyncio.sleep(0.5)

        except Exception as e:
            logger.error(f"Ошибка при отправке для chat_id {chat_id}: {e}")



    return success_count


async def send_all_filtered_notices(filtered_notices):
    """Отправляет все отфильтрованные уведомления"""
    total_sent = 0

    for notice in filtered_notices:
        sent_count = await send_notifications(notice)
        if sent_count > 0:
            total_sent += 1

        # Задержка между разными закупками
        await asyncio.sleep(2)

    return total_sent


async def scrape_mimz_async():
    """Асинхронная функция для скрапинга МИМЗ с исправленной навигацией"""

    notices_data = []
    current_page = 1
    today = date.today()
    today_formatted = today.strftime("%d.%m.%Y")
    should_continue = True

    if platform.system() == "Windows":
        chrome_paths = [
            "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
            "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
            os.path.expanduser("~\\AppData\\Local\\Google\\Chrome\\Application\\chrome.exe")
            ]
    else:  # Linux/macOS
        chrome_paths = [
            "/usr/bin/google-chrome",
            "/usr/bin/chromium-browser",
            "/usr/bin/chromium",
            "/snap/bin/chromium",
            "/usr/bin/google-chrome-stable",
            "/opt/google/chrome/chrome",
            "/usr/local/bin/chrome",
            "/usr/local/bin/chromium"
            ]

    chrome_path = None
    for path in chrome_paths:
        if os.path.exists(path):
            chrome_path = path
            break

    if not chrome_path:
        logger.error("Chrome не найден")
        return []

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            executable_path=chrome_path
            )
        context = await browser.new_context(ignore_https_errors=True)
        page = await context.new_page()

        async def handle_response(response):
            nonlocal notices_data
            if "NoticesJson" in response.url:
                try:
                    data = await response.json()
                    page_notices = []
                    if isinstance(data, list):
                        page_notices = data
                    elif isinstance(data, dict):
                        if 'data' in data:
                            page_notices = data['data']
                        elif 'items' in data:
                            page_notices = data['items']
                        elif 'notices' in data:
                            page_notices = data['notices']
                        else:
                            page_notices = [data]

                    notices_data.extend(page_notices)
                except Exception as e:
                    logger.error(f"Ошибка парсинга JSON: {e}")

        page.on("response", handle_response)

        # Переходим на первую страницу
        await page.goto("https://mimz.admoblkaluga.ru/GzwSP/NoticesGrid")
        await page.wait_for_load_state("networkidle")
        await page.wait_for_timeout(3000)

        while should_continue:
            try:
                await page.wait_for_timeout(2000)

                publication_date_found = False
                dates_on_page = []

                try:
                    date_captions = await page.query_selector_all("span.caption:has-text('Дата публикации')")

                    for i, caption in enumerate(date_captions):
                        try:
                            parent_td = await caption.query_selector("xpath=..")
                            if parent_td:
                                spans_in_td = await parent_td.query_selector_all("span")

                                for span in spans_in_td:
                                    # ИСПРАВЛЕНИЕ: await только для async метода
                                    span_text_raw = await span.inner_text()
                                    span_text = span_text_raw.strip()

                                    date_match = re.match(r'^(\d{1,2})\.(\d{1,2})\.(\d{4})$', span_text)
                                    if date_match:
                                        day, month, year = map(int, date_match.groups())
                                        try:
                                            parsed_date = date(year, month, day)
                                            dates_on_page.append(parsed_date)
                                            if parsed_date == today:
                                                publication_date_found = True
                                        except ValueError:
                                            continue
                        except Exception as block_error:
                            logger.error(f"⚠️ Ошибка при обработке блока даты {i + 1}: {block_error}")
                            continue

                except Exception as search_error:
                    logger.error(f"⚠️ Ошибка при поиске блоков дат публикации: {search_error}")

                # Логика остановки: если на странице нет сегодняшних дат
                if not publication_date_found:
                    if dates_on_page and all(d < today for d in dates_on_page):
                        break

            except Exception as e:
                logger.error(f"⚠Ошибка при проверке дат: {e}")

            # Поиск кнопки следующей страницы
            next_button = None
            try:
                next_button = await page.query_selector("span.page.next:not(:has(span:text-is(' ')))")

                if not next_button:
                    next_page_selector = f"span.page[value='{current_page}']:not(.active)"
                    next_button = await page.query_selector(next_page_selector)

                if not next_button:
                    active_page = await page.query_selector("span.page.active")
                    if active_page:
                        active_value = await active_page.get_attribute("value")
                        if active_value is not None:
                            next_value = int(active_value) + 1
                            next_button = await page.query_selector(f"span.page[value='{next_value}']")

            except Exception as e:
                logger.error(f"Ошибка поиска кнопки пагинации: {e}")

            if not next_button:
                break

            # Переходим на следующую страницу
            try:
                await next_button.click()
                await page.wait_for_load_state("networkidle")
                await page.wait_for_timeout(3000)

                # ИСПРАВЛЕНИЕ: добавить await
                new_active = await page.query_selector("span.page.active")
                if new_active:
                    new_active_value = await new_active.get_attribute("value")
                    if new_active_value:
                        actual_page = int(new_active_value) + 1
                        current_page = actual_page
                    else:
                        current_page += 1
                else:
                    current_page += 1

                await page.wait_for_timeout(2000)

            except Exception as e:
                logger.error(f"Ошибка при переходе на следующую страницу: {e}")
                break

            if current_page > 50:
                break

    # Фильтрация по сегодняшней дате (вне блока async with)
    today_notices = []
    today_str = today.strftime("%d.%m.%Y")

    for notice in notices_data:
        if 'pub_date' in notice and notice['pub_date'] == today_str:
            today_notices.append(notice)

    return today_notices


async def periodic_check_mimz():

    while True:
        try:

            # Загружаем ключевые слова и исключения
            keywords = load_keywords()

            # Выполняем скрапинг в отдельном потоке
            # Выполняем асинхронный скрапинг
            notices_data = await scrape_mimz_async()

            if notices_data:

                today_notices = filter_by_today_date(notices_data)
                if not today_notices:
                    logger.info("Нет закупок за сегодняшнюю дату")
                else:

                    filtered_notices, found_count = await filter_notices(notices_data, keywords)

                    if filtered_notices:
                        await send_all_filtered_notices(filtered_notices)
                    else:
                        logger.info("Нет новых закупок для отправки")
            else:
                logger.info("Данные не получены")

        except Exception as e:
            logger.error(f"Ошибка при проверке МИМЗ: {e}")

        logger.info("Следующая проверка МИМЗ через 5 минут...")
        await asyncio.sleep(300)


