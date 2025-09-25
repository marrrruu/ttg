import os
import logging
from flask import Flask, request, jsonify
import requests
import json
import bcrypt
from huggingface_hub import HfApi, HfFileSystem 


# логирование
logging.basicConfig(
    level=logging.DEBUG, 
    format='%(asctime)s - %(levelname)s - %(message)s',
    encoding='utf-8'
)
logger = logging.getLogger(__name__)



from your_model_module import load_model, predict_image


HF_TOKEN = os.getenv("HF_TOKEN")
HF_DATASET_REPO_ID = os.getenv("HF_DATASET_REPO_ID")
USERS_DB_FILE_IN_DATASET = 'users_db.json' 


#  API клиенты для HF
api = HfApi() # Для загрузки/скачивания файлов
fs = HfFileSystem() # Для работы с файловой системой HF


def load_users_db():

    try:
        with fs.open(f"datasets/{HF_DATASET_REPO_ID}/{USERS_DB_FILE_IN_DATASET}", "r") as f:
            data = json.load(f)
            return data
    except Exception as e:
        logger.error(f"Ошибка при загрузке {HF_DATASET_REPO_ID}: {e}")
        return {} 

def save_users_db(db):

    local_temp_path = os.path.join("/tmp", USERS_DB_FILE_IN_DATASET)
    
    try:
        with open(local_temp_path, 'w', encoding='utf-8') as f:
            json.dump(db, f, indent=4, ensure_ascii=False) # ensure_ascii=False для кириллицы   
        # Загружаем файл в  HF
        api.upload_file(
            path_or_fileobj=local_temp_path,          # Локальный путь к файлу для загрузки
            path_in_repo=USERS_DB_FILE_IN_DATASET,    # Путь к файлу внутри репозитория HF
            repo_id=HF_DATASET_REPO_ID,               # ID репозитория набора данных
            repo_type="dataset",                      # Тип репозитория
            token=HF_TOKEN,                           # Токен для авторизации
            commit_message=f"Update {USERS_DB_FILE_IN_DATASET}" # Сообщение 
        )
    except Exception as e:
        logger.error(f"Ошибка при сохранении в набор данных {HF_DATASET_REPO_ID}: {e}")
    finally:
        # удалить временный файл
        if os.path.exists(local_temp_path):
            os.remove(local_temp_path)
            logger.debug(f"Временный файл {local_temp_path} удален.")



users_db = load_users_db()

try:
    model = load_model('human_monkey_model.h5') 
    logger.info("Модель успешно загружена.")
except Exception as e:
    logger.error(f"Не удалось загрузить модель': {e}")
    model = None 


app = Flask(__name__)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8030022966:AAF8FsLoa9IItBXCxRsmTBtyqmoStBo7uWI")


def send_telegram_message(chat_id, text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {'chat_id': chat_id, 'text': text}
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status() # Вызывает исключение для HTTP ошибок (4xx или 5xx)
        logger.info(f"Сообщение отправлено в чат {chat_id}: {text}")
    except requests.exceptions.RequestException as e:
        logger.error(f"Ошибка при отправке сообщения в Telegram для chat_id {chat_id}: {e}")

def handle_start_command(chat_id):
    """Обрабатывает команду /start."""
    response_text = (
        'Привет! Я бот для классификации изображений.\n'
        'Команды:\n'
        '/register - регистрация\n'
        '/login - вход\n'
        '/predict - классификация изображения\n'
        '/logout - выход\n'
        '/cancel - отмена операции'
    )
    send_telegram_message(chat_id, response_text)

def handle_password_logic(chat_id, user_input_text, command_type):
    password = user_input_text.encode('utf-8')  # пароли — байты

    if command_type == 'register':
        if chat_id in users_db and users_db[chat_id].get('password'):
            send_telegram_message(chat_id, "Вы уже зарегистрированы. Используйте /login для входа.")
        else:
            hashed_pw = bcrypt.hashpw(password, bcrypt.gensalt()).decode('utf-8')
            users_db[chat_id] = {'password': hashed_pw, 'logged_in': False, 'state': None}
            save_users_db(users_db)
            send_telegram_message(chat_id, "Вы успешно зарегистрированы! Теперь используйте /login для входа.")

    elif command_type == 'login':
        stored_hashed_pw = users_db.get(chat_id, {}).get('password', '').encode('utf-8')
        if stored_hashed_pw and bcrypt.checkpw(password, stored_hashed_pw):
            users_db[chat_id]['logged_in'] = True
            save_users_db(users_db)
            send_telegram_message(chat_id, "Вы успешно вошли в систему!")
        else:
            send_telegram_message(chat_id, "Неверный пароль или вы не зарегистрированы.")

# обработчик вебхука 

@app.route(f'/{TELEGRAM_BOT_TOKEN}', methods=['POST'])
def telegram_webhook():        
    update = request.get_json()

    if 'message' not in update:
        logger.info("Получено обновление без поля 'message'.")
        return jsonify({"status": "ok"}), 200

    message = update['message']
    chat_id = str(message['chat']['id']) 
    text = message.get('text')
    photo_info = message.get('photo')

    # инициализация пользователя, если его нет в БД
    if chat_id not in users_db:
        users_db[chat_id] = {'state': None, 'logged_in': False, 'password': None} 
        save_users_db(users_db) 

    current_user_state = users_db[chat_id].get('state', None) # получаем текущее состояние пользователя

    if text:
        logger.info(f"Получено текстовое сообщение от {chat_id}: '{text}' в состоянии '{current_user_state}'")
        
        # Обработка команд
        if text == '/start':
            handle_start_command(chat_id)
            users_db[chat_id]['state'] = None 
            users_db[chat_id]['logged_in'] = False 
            save_users_db(users_db)
        elif text == '/register':
            send_telegram_message(chat_id, "Введите ваш пароль для регистрации:")
            users_db[chat_id]['state'] = 'awaiting_register_password' 
            save_users_db(users_db)
        elif text == '/login':
            send_telegram_message(chat_id, "Введите ваш пароль для входа:")
            users_db[chat_id]['state'] = 'awaiting_login_password' 
            save_users_db(users_db)
        elif text == '/predict':
            if users_db.get(chat_id, {}).get('logged_in'):
                send_telegram_message(chat_id, "Отправьте изображение для классификации.")
                users_db[chat_id]['state'] = 'awaiting_image_for_predict' 
                save_users_db(users_db)
            else:
                send_telegram_message(chat_id, "Для классификации изображения необходимо войти в систему. Используйте /login.")
                users_db[chat_id]['state'] = None 
                save_users_db(users_db)
        elif text == '/logout':
            if chat_id in users_db:
                users_db[chat_id]['logged_in'] = False
                users_db[chat_id]['state'] = None 
                save_users_db(users_db)
                send_telegram_message(chat_id, "Вы вышли из системы.")
            else:
                send_telegram_message(chat_id, "Вы не были авторизованы.")
        elif text == '/cancel':
            if chat_id in users_db:
                users_db[chat_id]['state'] = None 
                save_users_db(users_db)
            send_telegram_message(chat_id, "Операция отменена.")
        
        # Обработка ответов на запросы (на основе текущего состояния)
        elif current_user_state == 'awaiting_register_password':
            handle_password_logic(chat_id, text, 'register')
            users_db[chat_id]['state'] = None 
            save_users_db(users_db)
        elif current_user_state == 'awaiting_login_password':
            handle_password_logic(chat_id, text, 'login')
            users_db[chat_id]['state'] = None 
            save_users_db(users_db)
        else:
            send_telegram_message(chat_id, "Я не понимаю эту команду.")

    # обработка фотки
    elif photo_info:
        if current_user_state == 'awaiting_image_for_predict':
            if users_db.get(chat_id, {}).get('logged_in'): 
                if model:
                    file_id = photo_info[-1]['file_id'] # берем самое большое разрешение фотки
                    
                    # получаем информацию о фотке
                    file_url_info = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getFile?file_id={file_id}"
                    
                    # временная директория
                    temp_dir = "/tmp"
                    image_filename = os.path.join(temp_dir, f"temp_image_{file_id}.jpg") # имя фотки
                    
                    try:
                        file_response = requests.get(file_url_info).json() #метаданные фотки
                        if file_response['ok']:
                            file_path_on_telegram = file_response['result']['file_path'] #путь до фотки
                            download_url = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_path_on_telegram}" #путь загрузки

                
                            image_data = requests.get(download_url).content #скачиваем
                            
                            # сохраняем изображение во временный файл
                            with open(image_filename, 'wb') as f:
                                f.write(image_data)

                            # модель
                            prediction, confidence = predict_image(model, image_filename)
                            send_telegram_message(chat_id, f'На изображении: {prediction}\nУверенность: {confidence:.2%}')
                        else:
                            send_telegram_message(chat_id, "Ошибка при загрузке информации.")
                    except Exception as e:
                        error_message_to_user = 'Произошла ошибка при обработке изображения.'
                        send_telegram_message(chat_id, error_message_to_user)
                    finally:
                        if os.path.exists(image_filename):
                            os.remove(image_filename)
                            logger.info(f"Временный файл {image_filename} удален.")
                else:
                    send_telegram_message(chat_id, "Модель классификации недоступна.")
            else:
                send_telegram_message(chat_id, "Вы должны быть авторизованы, чтобы отправлять изображения. Используйте /login.")
            
            users_db[chat_id]['state'] = None 
            save_users_db(users_db)

        else:
            send_telegram_message(chat_id, "Я не ожидал изображение сейчас. Возможно, вам нужно использовать команду /predict.")
    

    else:
       
        send_telegram_message(chat_id, "Используйте команды или отправьте изображение после /predict.")

    # всегда возвращаем 200 OK для Telegram
    return jsonify({"status": "ok"}), 200


if __name__ == '__main__':
    # Flask будет слушать порт, который Hugging Face Spaces проксирует
    app.run(host='0.0.0.0', port=7860)
