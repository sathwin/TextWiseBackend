import os
import time
import requests
import openai
import json
import nltk
import sqlite3
from langdetect import detect
import datetime

# === Configuration ===

# Fetch API keys from environment variables (recommended for security)
OPENAI_API_KEY="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"
TEXTBEE_API_KEY="84d9cf32-3f8d-4237-a608-adab6363f7bf"
TEXTBEE_DEVICE_ID="671dc08e30206fdc681d8f13"
# Ensure that all API keys are provided
if not OPENAI_API_KEY or not TEXTBEE_API_KEY or not TEXTBEE_DEVICE_ID:
    print("Error: Missing API keys. Please set OPENAI_API_KEY, TEXTBEE_API_KEY, and TEXTBEE_DEVICE_ID environment variables.")
    exit(1)

# Set the OpenAI API key
openai.api_key = OPENAI_API_KEY

# Initialize the SQLite database
conn = sqlite3.connect('conversation_history.db')
cursor = conn.cursor()

# Create the users table if it doesn't exist
cursor.execute('''
CREATE TABLE IF NOT EXISTS users (
    sender_number TEXT PRIMARY KEY,
    understanding_level INTEGER
)
''')
conn.commit()

# Download necessary NLTK data
nltk.download('punkt')

# TextBee API endpoints
TEXTBEE_BASE_URL = 'https://api.textbee.dev/api/v1/gateway'
GET_RECEIVED_SMS_URL = f'{TEXTBEE_BASE_URL}/devices/{TEXTBEE_DEVICE_ID}/getReceivedSMS'
SEND_SMS_URL = f'{TEXTBEE_BASE_URL}/devices/{TEXTBEE_DEVICE_ID}/sendSMS'

# Path to store the last processed message ID
LAST_PROCESSED_TIMESTAMP_FILE = 'last_processed_timestamp.txt'

# === Functions ===

def get_received_sms():
    """
    Fetch received SMS messages from TextBee API.
    """
    headers = {
        'x-api-key': TEXTBEE_API_KEY,
    }

    try:
        response = requests.get(GET_RECEIVED_SMS_URL, headers=headers)
        response.raise_for_status()
        # Parse the JSON response
        messages_json = response.json()
        # Extract the list of messages
        messages = messages_json.get('data', [])
        return messages
    except requests.exceptions.RequestException as e:
        print(f"Error fetching received SMS: {e}")
        return []


def process_message_with_openai(sender_number, message_text, understanding_level):
    """
    Send the message text to OpenAI API and get the response.
    Maintain conversation history per sender in the database.
    Adjust response complexity based on understanding level.
    """
    # Detect the language of the incoming message
    try:
        language = detect(message_text)
    except:
        language = 'en'  # Default to English if detection fails

    # Fetch conversation history from the database
    cursor.execute('SELECT role, content FROM conversations WHERE sender_number = ? ORDER BY timestamp', (sender_number,))
    history = [{'role': row[0], 'content': row[1]} for row in cursor.fetchall()]

    # Add the user's message to the history
    history.append({"role": "user", "content": message_text})

    # Prepare the messages for OpenAI API
    system_message = "You are a helpful assistant that answers questions via SMS."

    # Adjust the assistant's behavior based on understanding level
    if understanding_level == 1:
        system_message += " Provide explanations suitable for a beginner learner. Keep it simple and avoid jargon. 😊"
    elif understanding_level == 2:
        system_message += " Explain concepts in a straightforward manner with basic terminology."
    elif understanding_level == 3:
        system_message += " Provide detailed explanations with examples."
    elif understanding_level == 4:
        system_message += " Offer in-depth insights and discuss advanced aspects of the topic."
    elif understanding_level == 5:
        system_message += " Provide comprehensive and technical explanations suitable for an expert. 🧠"

    # If the language is not English, instruct the assistant to respond in the detected language
    if language != 'en':
        system_message += f" Respond in {language}."

    messages = [
        {"role": "system", "content": system_message}
    ] + history

    try:
        response = openai.ChatCompletion.create(
            model='gpt-4',
            messages=messages,
            max_tokens=600,
            temperature=0.7,
        )
        assistant_reply = response.choices[0].message.content.strip()

        # Add both the user's message and assistant's reply to the database
        cursor.execute('INSERT INTO conversations (sender_number, role, content) VALUES (?, ?, ?)',
                       (sender_number, 'user', message_text))
        cursor.execute('INSERT INTO conversations (sender_number, role, content) VALUES (?, ?, ?)',
                       (sender_number, 'assistant', assistant_reply))
        conn.commit()

        return assistant_reply
    except Exception as e:
        print(f"Error processing message with OpenAI: {e}")
        return "Sorry, I'm unable to process your request at the moment."

def split_message_into_sms(message_text):
    """
    Split the message into SMS segments without breaking words or sentences.
    """
    import nltk
    nltk.download('punkt', quiet=True)
    nltk.download('punkt_tab', quiet=True)

    max_total_length = 600  # Maximum total message length
    max_sms_length = 160    # Maximum length per SMS

    # Truncate the message if it exceeds the maximum total length
    message_text = message_text[:max_total_length]

    # Tokenize the message into sentences
    sentences = nltk.tokenize.sent_tokenize(message_text, language='english')

    sms_messages = []
    current_sms = ''
    for sentence in sentences:
        # If adding the sentence exceeds the max SMS length
        if len(current_sms) + len(sentence) + 1 > max_sms_length:
            sms_messages.append(current_sms.strip())
            current_sms = sentence + ' '
        else:
            current_sms += sentence + ' '

    # Add any remaining text to the SMS messages
    if current_sms:
        sms_messages.append(current_sms.strip())

    # Add sequence indicators if more than one SMS
    if len(sms_messages) > 1:
        total_parts = len(sms_messages)
        sms_messages = [f"({i+1}/{total_parts}) {sms}" for i, sms in enumerate(sms_messages)]

    return sms_messages

def send_sms(recipient_number, message_text):
    """
    Send an SMS or multiple SMS via TextBee API.
    """
    sms_messages = split_message_into_sms(message_text)
    headers = {
        'x-api-key': TEXTBEE_API_KEY,
        'Content-Type': 'application/json',
    }

    for sms in sms_messages:
        data = {
            'recipients': [recipient_number],
            'message': sms,
        }

        try:
            response = requests.post(SEND_SMS_URL, headers=headers, json=data)
            response.raise_for_status()
            print(f"Sent SMS to {recipient_number}: {sms}")
        except requests.exceptions.RequestException as e:
            print(f"Error sending SMS to {recipient_number}: {e}")

def load_last_processed_timestamp():
    """
    Load the last processed message timestamp from a file.
    If the file doesn't exist, set it to the current time.
    """
    if os.path.exists(LAST_PROCESSED_TIMESTAMP_FILE):
        with open(LAST_PROCESSED_TIMESTAMP_FILE, 'r') as file:
            return file.read().strip()
    else:
        # Initialize with the current time minus a small buffer
        current_time = (datetime.datetime.utcnow() - datetime.timedelta(seconds=5)).strftime('%Y-%m-%dT%H:%M:%S.%fZ')
        return current_time

def save_last_processed_timestamp(timestamp):
    """
    Save the last processed message timestamp to a file.
    """
    with open(LAST_PROCESSED_TIMESTAMP_FILE, 'w') as file:
        file.write(timestamp)

# === Main Execution Loop ===
def clear_conversation_history():
    """
    Clear the conversation history from the database.
    """
    cursor.execute('DELETE FROM conversations')
    conn.commit()

def main():
    """
    Main loop to continuously check for new messages and respond.
    """
    print("Starting TextWise Backend Service...")
    last_processed_timestamp = load_last_processed_timestamp()

    while True:
        messages = get_received_sms()

        if not messages:
            # No messages received
            time.sleep(5)
            continue

        # Convert last_processed_timestamp to datetime object
        last_timestamp_dt = datetime.datetime.strptime(last_processed_timestamp, '%Y-%m-%dT%H:%M:%S.%fZ')

        # Process messages that are newer than last_processed_timestamp
        new_messages = []
        for message in messages:
            message_timestamp = message.get('receivedAt')
            message_timestamp_dt = datetime.datetime.strptime(message_timestamp, '%Y-%m-%dT%H:%M:%S.%fZ')
            if message_timestamp_dt > last_timestamp_dt:
                new_messages.append(message)

        # Sort new messages by timestamp
        new_messages.sort(key=lambda x: x.get('receivedAt', ''))

        for message in new_messages:
            message_id = message.get('_id')
            message_timestamp = message.get('receivedAt')
            sender_number = message.get('sender')
            message_text = message.get('message').strip()
            print(f"Received SMS from {sender_number}: {message_text}")

            # Check if user is in the middle of setting understanding level
            cursor.execute('SELECT understanding_level FROM users WHERE sender_number = ?', (sender_number,))
            user_data = cursor.fetchone()

            if user_data is None:
                # New user, ask for understanding level
                prompt = "Welcome! 😊 To personalize your learning experience, please rate your understanding of this topic from 1 (beginner) to 5 (expert). 📊"
                send_sms(sender_number, prompt)
                # Insert user with null understanding_level
                cursor.execute('INSERT INTO users (sender_number, understanding_level) VALUES (?, ?)', (sender_number, None))
                conn.commit()
            elif user_data[0] is None:
                # User has not set understanding level yet
                try:
                    level = int(message_text)
                    if 1 <= level <= 5:
                        cursor.execute('UPDATE users SET understanding_level = ? WHERE sender_number = ?', (level, sender_number))
                        conn.commit()
                        reply = f"Great! 🎉 We'll tailor the content to your level {level} understanding."
                        send_sms(sender_number, reply)
                    else:
                        send_sms(sender_number, "Please enter a number between 1 and 5. 🔢")
                except ValueError:
                    send_sms(sender_number, "Please enter a valid number between 1 and 5. 🔢")
            else:
                # Existing user with understanding level set
                # Process the message with OpenAI
                reply_text = process_message_with_openai(sender_number, message_text, user_data[0])
                print(f"Replying with: {reply_text}")

                # Send the reply back via SMS
                send_sms(sender_number, reply_text)

            # Update the last processed timestamp
            save_last_processed_timestamp(message_timestamp)
            last_processed_timestamp = message_timestamp

        # Wait before polling again
        time.sleep(2)

if __name__ == "__main__":
    main()
