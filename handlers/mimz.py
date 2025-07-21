from http.client import responses
import re
from datetime import datetime, date
from playwright.sync_api import sync_playwright
import json
import time
import asyncio
from aiog import *
import re
import editabs
import init_clients
from simple_tg_md import convert_to_md2
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import openai
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

def filter_by_today_date(notices):
    """Фильтрует записи только по сегодняшней дате"""
    today = datetime.now().strftime("%d.%m.%Y")
    today_notices = []

    print(f"🗓️ Фильтруем по сегодняшней дате: {today}")

    for notice in notices:
        pub_date = notice.get('pub_date', '')
        if pub_date == today:
            today_notices.append(notice)
        else:
            print(f"⏭️ Пропускаем запись с датой {pub_date}: {notice.get('number', 'Unknown')}")

    print(f"📅 Найдено {len(today_notices)} записей за сегодня из {len(notices)} общих")
    return today_notices



async def filter_notices(notices, keywords):
    """Фильтрует уведомления по ключевым словам и исключениям и сразу отправляет в ТГ"""
    sent_count = 0
    filtered_notices = []

    for notice in notices:
        # Объединяем текст для поиска
        search_text = f"{notice.get('name', '')} {notice.get('uchr_sname', '')}"


        number = notice.get('number', '')
        if not number or number.strip() == '' or number == 'N/A':
            print(f"⚠️ Пропускаем закупку без номера: {notice.get('name', 'Unknown')}")

        if  editabs.check(number, fz=None):
            print(f"🔁 Закупка {number} уже отправлена ранее")
            continue

        if number:
            editabs.save(number, fz=None)
            print(f"💾 Номер {number} сохранен")

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
            # Формируем ссылку
            full_url = f"https://mimz.admoblkaluga.ru/GzwSP/Notice?noticeLink={notice['link']}"

            # Формируем текст сообщения
            text = f"""🔔 Новая закупка с сайта  МИМЗ
            
            📝 *Номер:* {convert_to_md2(notice.get('number', 'N/A'))}
            📋 *Наименование:* {convert_to_md2(notice.get('name', 'N/A'))}
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
            print(f"✅ Отправлено для chat_id: {chat_id}")

            # Небольшая задержка между пользователями
            await asyncio.sleep(0.5)

        except Exception as e:
            print(f"❌ Ошибка при отправке для chat_id {chat_id}: {e}")



    return success_count


async def send_all_filtered_notices(filtered_notices):
    """Отправляет все отфильтрованные уведомления"""
    total_sent = 0

    for notice in filtered_notices:
        print(f"📤 Отправляем: {notice.get('number')} - {notice.get('name')}")
        sent_count = await send_notifications(notice)
        if sent_count > 0:
            total_sent += 1

        # Задержка между разными закупками
        await asyncio.sleep(2)

    print(f"🏁 Отправлено {total_sent} закупок из {len(filtered_notices)}")
    return total_sent


def scrape_mimz_sync():
    """Синхронная функция для скрапинга МИМЗ с исправленной навигацией"""

    notices_data = []
    current_page = 1
    today = date.today()
    today_formatted = today.strftime("%d.%m.%Y")
    should_continue = True


    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            executable_path="/snap/bin/chromium"
            )
        context = browser.new_context(ignore_https_errors=True)
        page = context.new_page()

        def handle_response(response):
            nonlocal notices_data
            if "NoticesJson" in response.url:
                print(f"📥 Получен ответ на странице {current_page}: {response.url}")
                try:
                    data = response.json()
                    print(f"📊 Тип данных: {type(data)}")

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
                    print(f"📋 Добавлено {len(page_notices)} записей со страницы {current_page}")

                except Exception as e:
                    print(f"❌ Ошибка парсинга JSON: {e}")

        page.on("response", handle_response)

        # Переходим на первую страницу
        print("🌐 Загружаем первую страницу...")
        page.goto("https://mimz.admoblkaluga.ru/GzwSP/NoticesGrid")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(3000)

        while should_continue:

            # Проверяем даты публикации на текущей странице
            try:
                page.wait_for_timeout(2000)

                publication_date_found = False
                dates_on_page = []

                try:
                    date_captions = page.query_selector_all("span.caption:has-text('Дата публикации')")
                    print(f"📦 Найдено {len(date_captions)} блоков 'Дата публикации'")

                    for i, caption in enumerate(date_captions):
                        try:
                            parent_td = caption.query_selector("xpath=..")
                            if parent_td:
                                spans_in_td = parent_td.query_selector_all("span")

                                for span in spans_in_td:
                                    span_text = span.inner_text().strip()
                                    date_match = re.match(r'^(\d{1,2})\.(\d{1,2})\.(\d{4})$', span_text)
                                    if date_match:
                                        day, month, year = map(int, date_match.groups())
                                        try:
                                            parsed_date = date(year, month, day)
                                            dates_on_page.append(parsed_date)
                                            print(f"📅 Найдена дата публикации в блоке {i + 1}: {parsed_date}")

                                            if parsed_date == today:
                                                publication_date_found = True
                                                print(f"✅ Найдена сегодняшняя дата публикации: {parsed_date}")

                                        except ValueError:
                                            continue

                        except Exception as block_error:
                            print(f"⚠️ Ошибка при обработке блока даты {i + 1}: {block_error}")
                            continue

                except Exception as search_error:
                    print(f"⚠️ Ошибка при поиске блоков дат публикации: {search_error}")

                print(f"📅 Найдено дат публикации на странице: {len(dates_on_page)}")
                if dates_on_page:
                    dates_sorted = sorted(dates_on_page)
                    print(f"📅 Диапазон дат: {dates_sorted[0]} - {dates_sorted[-1]}")

                # Логика остановки: если на странице нет сегодняшних дат
                if not publication_date_found:
                    if dates_on_page and all(d < today for d in dates_on_page):
                        print("⏹️ Все даты публикации на странице старше сегодняшней, останавливаемся")
                        break

            except Exception as e:
                print(f"⚠️ Ошибка при проверке дат: {e}")

            next_button = None
            try:
                # Сначала пробуем найти кнопку "следующая страница" (span.page.next)
                next_button = page.query_selector("span.page.next:not(:has(span:text-is(' ')))")

                if not next_button:
                    # Если кнопка next недоступна, ищем span с номером следующей страницы
                    # Текущая страница имеет класс active, нам нужна следующая
                    next_page_selector = f"span.page[value='{current_page}']:not(.active)"
                    next_button = page.query_selector(next_page_selector)

                    if next_button:
                        print(f"✅ Найдена кнопка страницы {current_page + 1}")

                if not next_button:
                    # Альтернативный способ: найти активную страницу и взять следующую
                    active_page = page.query_selector("span.page.active")
                    if active_page:
                        active_value = active_page.get_attribute("value")
                        if active_value is not None:
                            next_value = int(active_value) + 1
                            next_button = page.query_selector(f"span.page[value='{next_value}']")
                            if next_button:
                                print(f"✅ Найдена кнопка по значению value={next_value}")

            except Exception as e:
                print(f"⚠️ Ошибка поиска кнопки пагинации: {e}")

            if not next_button:
                print("⏹️ Кнопка следующей страницы не найдена, завершаем")
                break

            # Переходим на следующую страницу
            try:
                print(f"🔄 Переходим на страницу {current_page + 1}")

                # Запоминаем количество записей до перехода
                notices_before = len(notices_data)

                # Кликаем по span элементу
                next_button.click()

                # Ждем загрузки новой страницы
                page.wait_for_load_state("networkidle")
                page.wait_for_timeout(3000)

                # Проверяем, что страница действительно изменилась
                # Ищем новый активный элемент
                new_active = page.query_selector("span.page.active")
                if new_active:
                    new_active_value = new_active.get_attribute("value")
                    if new_active_value:
                        actual_page = int(new_active_value) + 1  # value начинается с 0
                        print(f"📍 Текущая активная страница: {actual_page}")
                        current_page = actual_page
                    else:
                        current_page += 1
                else:
                    current_page += 1

                # Дополнительное ожидание для AJAX-запросов
                page.wait_for_timeout(2000)

                # Проверяем, появились ли новые данные
                notices_after = len(notices_data)
                new_notices = notices_after - notices_before

                if new_notices > 0:
                    print(f"✅ Получено {new_notices} новых записей после перехода")
                else:
                    print("⚠️ Новые записи не получены через AJAX")

            except Exception as e:
                print(f"❌ Ошибка при переходе на следующую страницу: {e}")
                break

            # Защита от бесконечного цикла
            if current_page > 50:
                print("⚠️ Достигнут лимит страниц (50), останавливаемся")
                break

        browser.close()

        print(f"✅ Итого собрано {len(notices_data)} записей с {current_page} страниц")

    today_notices = []
    today_str  = today.strftime("%d.%m.%Y")

    for notice in notices_data:
        if 'pub_date' in notice and notice['pub_date'] == today_str:
            today_notices.append(notice)

    print(f"✅ Найдено {len(today_notices)} записей за сегодня из {len(notices_data)} общих")

    return today_notices


async def periodic_check_mimz():

    while True:
        try:
            print(f"\n[{datetime.datetime.now()}] Начинаем проверку mimz")
            # Загружаем ключевые слова и исключения
            keywords = load_keywords()

            # Выполняем скрапинг в отдельном потоке
            loop = asyncio.get_event_loop()
            with ThreadPoolExecutor() as executor:
                notices_data = await loop.run_in_executor(executor, scrape_mimz_sync)

            if notices_data:
                print(f"Получено {len(notices_data)} закупок")
                today_notices = filter_by_today_date(notices_data)

                if not today_notices:
                    print("📅 Нет закупок за сегодняшнюю дату")
                else:
                    print("🔍 Пример данных за сегодня:")
                    for i, notice in enumerate(today_notices[:2]):
                        print(f"  Запись {i + 1}:")
                        print(f"    number: '{notice.get('number', 'MISSING')}'")

                    filtered_notices, found_count = await filter_notices(notices_data, keywords)
                    print(f"Найдено {found_count} подходящих закупок из {len(notices_data)} общих")

                    if filtered_notices:
                        sent_count = await send_all_filtered_notices(filtered_notices)
                        print(f"✅ МИМЗ: отправлено {sent_count} уведомлений")
                    else:
                        print("Нет новых закупок для отправки")
            else:
                print("Данные не получены")

        except Exception as e:
            print(f"❌ Ошибка при проверке МИМЗ: {e}")

        # Ждем перед следующей проверкой
        print("⏰ Следующая проверка МИМЗ через 5 минут...")
        await asyncio.sleep(300)


