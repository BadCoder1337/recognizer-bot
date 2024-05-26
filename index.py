import os.path
import sys

import logging
import requests
import telebot
import json
import os
import grpc

sys.path.insert(0, "./cloudapi")
import cloudapi.yandex.cloud.ai.stt.v3.stt_pb2 as stt_pb2
import cloudapi.yandex.cloud.ai.stt.v3.stt_service_pb2_grpc as stt_service_pb2_grpc

# Эндпоинты сервисов и данные для аутентификации

CHUNK_SIZE = 4000
API_TOKEN = os.environ['TELEGRAM_TOKEN']
FOLDER_ID = ''
IAM_TOKEN = ''

VISION_URL = 'https://ocr.api.cloud.yandex.net/ocr/v1/recognizeText'
SPEECHKIT_URL = 'https://stt.api.cloud.yandex.net/speech/v1/stt:recognize'
SPEECHKIT_SYNTHESIS_URL = 'https://tts.api.cloud.yandex.net/speech/v1/tts:synthesize'
FUNCTIONS_URL = 'https://serverless-functions.api.cloud.yandex.net/functions/v1'
GRPC_HOST = 'stt.api.cloud.yandex.net:443'

logger = telebot.logger
telebot.logger.setLevel(logging.INFO)
bot = telebot.TeleBot(API_TOKEN, threaded=False)

# Получение идентификатора каталога

def get_folder_id(iam_token, version_id):
    headers = {'Authorization': f'Bearer {iam_token}'}
    function_id_req = requests.get(f'{FUNCTIONS_URL}/versions/{version_id}', headers=headers)
    function_id_data = function_id_req.json()
    function_id = function_id_data['functionId']
    folder_id_req = requests.get(f'{FUNCTIONS_URL}/functions/{function_id}', headers=headers)
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
    bot.reply_to(message, "Отправь голосовое сообщение для расшифровки и перевода")

@bot.message_handler(func=lambda message: True, content_types=['voice'])
def echo_audio(message):
    file_id = message.voice.file_id
    file_info = bot.get_file(file_id)
    downloaded_file = bot.download_file(file_info.file_path)
    reply = bot.reply_to(message, "Обработка...")
    for content in audio_analyze_stream(IAM_TOKEN, downloaded_file):
        bot.edit_message_text(text=content, chat_id=reply.chat.id, message_id=reply.message_id)

# Распознавание речи

def _audio_analyze_stream(audio_data: bytes):
      # Задайте настройки распознавания.
    recognize_options = stt_pb2.StreamingOptions(
        recognition_model=stt_pb2.RecognitionModelOptions(
            audio_format=stt_pb2.AudioFormatOptions(container_audio_type=stt_pb2.ContainerAudioType.OGG_OPUS),
            text_normalization=stt_pb2.TextNormalizationOptions(
                text_normalization=stt_pb2.TextNormalizationOptions.TEXT_NORMALIZATION_ENABLED,
                profanity_filter=True,
                literature_text=False
            ),
            language_restriction=stt_pb2.LanguageRestrictionOptions(
                restriction_type=stt_pb2.LanguageRestrictionOptions.WHITELIST,
                language_code=['ru-RU']
            ),
            audio_processing_type=stt_pb2.RecognitionModelOptions.REAL_TIME
        )
    )

    # Отправьте сообщение с настройками распознавания.
    yield stt_pb2.StreamingRequest(session_options=recognize_options)

    # Прочитайте аудиофайл и отправьте его содержимое порциями.
    for i in range(0, len(audio_data), CHUNK_SIZE):
        yield stt_pb2.StreamingRequest(chunk=stt_pb2.AudioChunk(data=audio_data[i+CHUNK_SIZE]))


def audio_analyze_stream(iam_token: str, audio_data: bytes):
    cred = grpc.ssl_channel_credentials()
    channel = grpc.secure_channel(GRPC_HOST, cred)
    stub = stt_service_pb2_grpc.RecognizerStub(channel)
    # Отправьте данные для распознавания.
    iter = stub.RecognizeStreaming(_audio_analyze_stream(audio_data), metadata=(
    # Параметры для авторизации с IAM-токеном
        ('Authorization', f'Bearer {iam_token}'),
    ))  
    # Обработайте ответы сервера и выведите результат в консоль.
    try:
        for msg in iter:
            event_type, alternatives = msg.WhichOneof('Event'), None
            if event_type == 'partial' and len(msg.partial.alternatives) > 0:
                alternatives = [a.text for a in msg.partial.alternatives]
            if event_type == 'final':
                alternatives = [a.text for a in msg.final.alternatives]
            if event_type == 'final_refinement':
                alternatives = [a.text for a in msg.final_refinement.normalized_text.alternatives]
            print(f'type={event_type}, alternatives={alternatives}')
            if alternatives != None:
                yield alternatives[0]
    except grpc._channel._Rendezvous as err:
        yield f'Ошибка {err._state.code}'
