import re



def clean_telegram_message(text):
    # Удаляем HTML-теги
    text = re.sub('<.*?>', '', text)

    # Заменяем HTML-сущности
    html_entities = {
        '&laquo;': '«',
        '&raquo;': '»',
        '&nbsp;': ' ',
        '&amp;': '&',
        '&lt;': '<',
        '&gt;': '>',
        '&quot;': '"'
        }

    for entity, replacement in html_entities.items():
        text = text.replace(entity, replacement)

    # Нормализуем пробелы
    text = re.sub(r'\s+', ' ', text)
    text = text.strip()

    # Ограничиваем длину
    if len(text) > 4096:
        text = text[:4093] + "..."

    return text