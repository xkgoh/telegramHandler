import boto3
import requests
import json
import os
import math
import logging

import telegramHandlerDBWriter
from telegramHandlerHelper import sort_results_by_distance, filter_merchant_source_and_category, paginate_results, \
    format_json_response, create_reply_keyboard_page_markup, update_source_filters

# Global variables
TOKEN = os.environ['TELEGRAM_BOT_TOKEN']
CHEAPO_CHAT_ID = int(os.environ['CHEAPO_CHAT_ID'])
REGISTRATION_PASSPHRASE = os.environ['REGISTRATION_PASSPHRASE']
BASE_URL = "https://api.telegram.org/bot{}".format(TOKEN)
SOURCE_DESC_NUM_MAP = {"ENTR": 1, "CITI": 2, "OCBC": 3}
SOURCE_NUM_DESC_MAP = {1: "ENTR", 2: "CITI", 3: "OCBC"}
MAX_NUM_RESULTS_PER_PAGE = 20

# Logging configurations
LOGGING_LEVEL = int(os.environ['LOGGING_LEVEL'])
logger = logging.getLogger()
logger.setLevel(LOGGING_LEVEL)


# Invoke a lambda function and return the json data returned by the lambda function
def invoke_lambda_function(function_name, invocation_type, payload_string):
    lambda_client = boto3.client('lambda')
    invoke_response = lambda_client.invoke(FunctionName=function_name, InvocationType=invocation_type,
                                           Payload=payload_string)
    return json.loads(invoke_response['Payload'].read())


def authenticate_user(data, sender_telegram_id, first_name):
    if telegramHandlerDBWriter.get_from_user_table(sender_telegram_id) is None:
        if "text" in data["message"] and REGISTRATION_PASSPHRASE in str(data["message"]["text"]).lower():
            if telegramHandlerDBWriter.write_to_user_table(sender_telegram_id, first_name) == True:
                response = "Registration for " + str(sender_telegram_id) + " " + first_name + " successful."
                data = {"text": response.encode("utf8"), "chat_id": sender_telegram_id}
                requests.post(BASE_URL + "/sendMessage", data)
                logger.info(str(sender_telegram_id) + " " + first_name + " successfully registered.")
        return False
    return True


def acknowledge_callback_query(callback_query_id):
    reply_data = {"callback_query_id": callback_query_id}
    requests.post(BASE_URL + "/answerCallbackQuery", reply_data)
    logger.info("Callback query acknowledged.")
    return {"statusCode": 200}


def reply_or_edit_message_text(json_response, current_page, sources_filter, sources_available, source_chat_id, source_message_id, mode):
    markdown_reply = format_json_response(json_response)
    reply_markup = create_reply_keyboard_page_markup(current_page, int(math.ceil(float(json_response['totalItems']) / float(MAX_NUM_RESULTS_PER_PAGE))), int(json_response['searchRadius']), sources_filter, sources_available)
    reply_data = {"chat_id": source_chat_id, "text": markdown_reply.encode("utf8"), "parse_mode": "markdown", "reply_markup": json.dumps(reply_markup)}
    if mode == "REPLY":
        reply_data["reply_to_message_id"] = source_message_id
        function_name = "/sendMessage"
    elif mode == "EDIT":
        reply_data["message_id"] = source_message_id
        function_name = "/editMessageText"
    post_reply = requests.post(BASE_URL + function_name, reply_data)
    logger.info("Message replied / edited.")
    logger.debug(str(post_reply.text))


def update_result_cache(json_response, sources_filter, sources_available, source_chat_id, search_center_details=None):
    if search_center_details is not None:  # If it is an update to radius, i.e. new search, cache the entire search result
        json_response, sources_available = filter_merchant_source_and_category(json_response)  # Sources available can change w the new search
        json_response = sort_results_by_distance(json_response, search_center_details)
    json_response = update_source_filters(json_response, sources_filter, sources_available)
    telegramHandlerDBWriter.write_to_results_cache(source_chat_id, json_response)
    return sources_available, json_response  # Return the updated sources_available list and the cached json_response


def process_callback_query(data):
    source_message_id = data["callback_query"]["message"]["message_id"]
    source_chat_id = data["callback_query"]["message"]["chat"]["id"]
    callback_query_id = data["callback_query"]["id"]
    callback_query_data = data["callback_query"]["data"]

    cached_message = telegramHandlerDBWriter.get_from_result_cache(source_chat_id)
    cached_json_reply = json.loads(cached_message['Result'])
    data_sources = cached_json_reply['sourcesFilter']
    original_sources_available = cached_json_reply['sourcesAvailable']
    search_center_details = {"latitude": cached_json_reply["searchCenterLatitude"],
                             "longitude": cached_json_reply["searchCenterLongitude"]}

    current_page = 1  # Reset the page number

    if str(callback_query_data).isdigit():  # If it is a change in page number or radius
        callback_query_data = int(callback_query_data)

        if callback_query_data >= 250:  # If it involves changes to the radius
            search_radius = callback_query_data
            search_center_details['searchRadius'] = int(search_radius)

            # Execute another search with the new radius
            json_response = invoke_lambda_function("queryGeoDatabase", "RequestResponse", json.dumps(search_center_details))
            original_sources_available, json_response = update_result_cache(json_response, data_sources, original_sources_available, source_chat_id, search_center_details=search_center_details)

        else:  # If its moving to the next page
            current_page = callback_query_data  # For moving to the next page, dont reset the page number
            json_response = cached_json_reply

    else:  # If filter of the data source
        callback_query_data = str(callback_query_data)

        # If it is the last filter remaining and callback query request to turn it off, or if the filter is not to be displayd, ignore it
        if (len(data_sources) <= 1 and SOURCE_DESC_NUM_MAP.get(callback_query_data) in data_sources) or callback_query_data == "NIL":
            return acknowledge_callback_query(callback_query_id)

        # Toggle the filter
        if SOURCE_DESC_NUM_MAP.get(callback_query_data) not in data_sources:
            data_sources.append(SOURCE_DESC_NUM_MAP.get(callback_query_data))
        else:
            data_sources.remove(SOURCE_DESC_NUM_MAP.get(callback_query_data))

        json_response = cached_json_reply  # There is no change to the json_response message
        original_sources_available, json_response = update_result_cache(json_response, data_sources, original_sources_available, source_chat_id, search_center_details=None)

    logger.debug("Callback query task defined.")
    logger.debug(json_response)

    json_response, sources_available = filter_merchant_source_and_category(json_response, data_sources)
    json_response = sort_results_by_distance(json_response, search_center_details)
    json_response = paginate_results(json_response, current_page)

    reply_or_edit_message_text(json_response, current_page, sources_available, original_sources_available, source_chat_id, source_message_id, "EDIT")

    return acknowledge_callback_query(callback_query_id)


def lambda_handler(event, context):
    try:
        logger.info("Starting Lambda Handler")
        data = json.loads(event["body"])

        logger.debug("Event object received:")
        logger.debug(event)

        if "callback_query" in data:
            return process_callback_query(data)

        # If it is replying to a message not sent by the chatbot, ignore it
        if "reply_to_message" in data["message"]:
            if data["message"]["reply_to_message"]["from"]["id"] != CHEAPO_CHAT_ID:
                logger.debug("Message not from Cheapo.")
                return {"statusCode": 200}

        sender_telegram_id = data["message"]["from"]["id"]
        chat_id = data["message"]["chat"]["id"]
        chat_type = data["message"]["chat"]["type"]
        source_message_id = data["message"]["message_id"]
        first_name = data["message"]["from"]["first_name"]  # Reply the user with his/her details

        if authenticate_user(data, sender_telegram_id, first_name) is False:
            return {"statusCode": 200}

        message = data["message"]

        if "text" in message:
            logger.debug("Text message detected.")
            reply_url = BASE_URL + "/sendMessage"
            if chat_type == "group" and str(message["text"]).lower() == "/hello":
                data = {"text": ("Hello I am Cheapo! Reply this message to talk to me!").encode("utf8"), "chat_id": chat_id, "reply_to_message_id": source_message_id}
                requests.post(reply_url, data)
            else:
                data = {"text": (" Hello I am Cheapo! Send me a location to get started!").encode("utf8"), "chat_id": chat_id, "reply_to_message_id": source_message_id}
                requests.post(reply_url, data)
            logger.debug("Text message processed.")

        if "location" in message:
            logger.debug("Location message detected.")
            json_response = invoke_lambda_function("queryGeoDatabase", "RequestResponse", json.dumps(message["location"]))

            # There is no filter for the initial result, hence is all possible sources
            sources_available, json_response = update_result_cache(json_response, SOURCE_DESC_NUM_MAP.values(),
                                                                   SOURCE_DESC_NUM_MAP.values(), chat_id,
                                                                   search_center_details=message["location"])
            json_response = paginate_results(json_response, 1)
            reply_or_edit_message_text(json_response, 1, sources_available, sources_available, chat_id, source_message_id, "REPLY")
            logger.debug("Location message processed.")

    except Exception as e:
        logger.error(str(e))

    logger.info("Terminating Lambda Handler")
    return {"statusCode": 200}