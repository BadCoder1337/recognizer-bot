import logging
import requests
import telebot
import json
import os
import base64

# Эндпоинты сервисов и данные для аутентификации

API_TOKEN = os.environ['TELEGRAM_TOKEN']
FOLDER_ID = ''
IAM_TOKEN = ''

VISION_URL = 'https://ocr.api.cloud.yandex.net/ocr/v1/recognizeText'
SPEECHKIT_URL = 'https://stt.api.cloud.yandex.net/speech/v1/stt:recognize'
SPEECHKIT_SYNTHESIS_URL = 'https://tts.api.cloud.yandex.net/speech/v1/tts:synthesize'
FUNCTIONS_URL = 'https://serverless-functions.api.cloud.yandex.net/functions/v1'

logger = telebot.logger
telebot.logger.setLevel(logging.INFO)
bot = telebot.TeleBot(API_TOKEN, threaded=False)

# Получение идентификатора каталога

def get_folder_id(iam_token, version_id):

    headers = {'Authorization': f'Bearer {iam_token}'}
    function_id_req = requests.get(f'{FUNCTIONS_URL}/versions/{version_id}',
                                   headers=headers)
    function_id_data = function_id_req.json()
    function_id = function_id_data['functionId']
    folder_id_req = requests.get(f'{FUNCTIONS_URL}/functions/{function_id}',
                                 headers=headers)
    folder_id_data = folder_id_req.json()
    folder_id = folder_id_data['folderId']
    return folder_id

def process_event(event):

    request_body_dict = json.loads(event['body'])
    update = telebot.types.Update.de_json(request_body_dict)

    bot.process_new_updates([update])

def handler(event, context):
    global IAM_TOKEN, FOLDER_ID
    IAM_TOKEN = context.token["access_token"]
    version_id = context.function_version
    FOLDER_ID = get_folder_id(IAM_TOKEN, version_id)
    process_event(event)
    return {
        'statusCode': 200
    }

# Обработчики команд и сообщений

@bot.message_handler(commands=['help', 'start'])
def send_welcome(message):
    bot.reply_to(message,
                 "Бот умеет:\n*распознавать текст с картинок;\n* генерировать голосовые сообщения из текста;\n* переводить голосовые сообщения в текст.")

@bot.message_handler(func=lambda message: True, content_types=['text'])
def echo_message(message):
    global IAM_TOKEN, FOLDER_ID
    with open('/tmp/audio.ogg', "wb") as f:
        for audio_content in synthesize(FOLDER_ID, IAM_TOKEN, message.text):
            f.write(audio_content)
    voice = open('/tmp/audio.ogg', 'rb')
    bot.send_voice(message.chat.id, voice)

@bot.message_handler(func=lambda message: True, content_types=['voice'])
def echo_audio(message):
    file_id = message.voice.file_id
    file_info = bot.get_file(file_id)
    downloaded_file = bot.download_file(file_info.file_path)
    response_text = audio_analyze(SPEECHKIT_URL, IAM_TOKEN, FOLDER_ID, downloaded_file)
    bot.reply_to(message, response_text)

@bot.message_handler(func=lambda message: True, content_types=['photo'])
def echo_photo(message):
    file_id = message.photo[-1].file_id
    file_info = bot.get_file(file_id)
    downloaded_file = bot.download_file(file_info.file_path)
    image_data = base64.b64encode(downloaded_file).decode('utf-8')
    response_text = image_analyze(VISION_URL, IAM_TOKEN, FOLDER_ID, image_data)
    bot.reply_to(message, response_text)

# Распознавание изображения

def image_analyze(vision_url, iam_token, folder_id, image_data):
    response = requests.post(vision_url, headers={'Authorization': 'Bearer '+iam_token, 'x-folder-id': folder_id}, json={
        "mimeType": "image",
        "languageCodes": ["en", "ru"],
        "model": "page",
        "content": image_data
        })
    blocks = response.json()['result']['textAnnotation']['blocks']
    text = ''
    for block in blocks:
        for line in block['lines']:
            for word in line['words']:
                text += word['text'] + ' '
            text += '\n'
    return text

# Распознавание речи

def audio_analyze(speechkit_url, iam_token, folder_id, audio_data):
    headers = {'Authorization': f'Bearer {iam_token}'}
    params = {
        "topic": "general",
        "folderId": f"{folder_id}",
        "lang": "ru-RU"}

    audio_request = requests.post(speechkit_url, params=params, headers=headers, data=audio_data)
    responseData = audio_request.json()
    response = 'error'
    if responseData.get("error_code") is None:
        response = (responseData.get("result"))
    return response

# Синтез речи

def synthesize(folder_id, iam_token, text):
   headers = {
       'Authorization': 'Bearer ' + iam_token,
   }

   data = {
       'text': text,
       'lang': 'ru-RU',
       'voice': 'filipp',
       'folderId': folder_id
   }

   with requests.post(SPEECHKIT_SYNTHESIS_URL, headers=headers, data=data, stream=True) as resp:
       if resp.status_code != 200:
           raise RuntimeError("Invalid response received: code: %d, message: %s" % (resp.status_code, resp.text))

       for chunk in resp.iter_content(chunk_size=None):
           yield chunk