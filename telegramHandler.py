import boto3
import requests
import json
import os
import math

import telegramHandlerDBWriter
from telegramHandlerHelper import sort_results_by_distance, filter_merchant_source_and_category, paginate_results, format_json_response, create_reply_keyboard_page_markup


RADIUS_CHANGE = 250  # Increasing or decreasing the radius changes it by 250 each time
MAX_SEARCH_RADIUS = 5000
MAX_NUM_RESULTS_PER_PAGE = 20
APPROVED_USER_STR = os.environ['APPROVED_USER_LIST']
TOKEN = os.environ['TELEGRAM_BOT_TOKEN']
BASE_URL = "https://api.telegram.org/bot{}".format(TOKEN)
SOURCE_DESC_NUM_MAP = {"ENTR": 1, "CITI": 2, "OCBC": 3}
SOURCE_NUM_DESC_MAP = {1: "ENTR", 2: "CITI", 3: "OCBC"}



# Invoke a lambda function and return the json data returned by the lambda function
def invoke_lambda_function(function_name, invocation_type, payload_string):
    lambda_client = boto3.client('lambda')
    invoke_response = lambda_client.invoke(FunctionName=function_name, InvocationType=invocation_type,
                                           Payload=payload_string)
    return json.loads(invoke_response['Payload'].read())


def acknowledge_callback_query(callback_query_id):
    print "executing call back query"
    reply_url = BASE_URL + "/answerCallbackQuery"
    reply_data = {"callback_query_id": callback_query_id}
    requests.post(reply_url, reply_data)
    print "executed callback query"
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
    print str(post_reply.text)


def update_source_filters(json_response, sources_filter, sources_available):
    sources_filter_set, sources_available_set = set(sources_filter), set(sources_available)
    json_response['sourcesFilter'] = list(sources_filter_set.intersection(sources_available_set))  # Filtered values can only contain values from the original sources
    json_response['sourcesAvailable'] = sources_available
    return json_response


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

    print "Trying to paginate "
    print json_response

    json_response, sources_available = filter_merchant_source_and_category(json_response, data_sources)
    json_response = sort_results_by_distance(json_response, search_center_details)
    json_response = paginate_results(json_response, current_page)

    print "paginate "

    reply_or_edit_message_text(json_response, current_page, sources_available, original_sources_available, source_chat_id, source_message_id, "EDIT")

    return acknowledge_callback_query(callback_query_id)



def lambda_handler(event, context):
    try:
        print "Initializaing Handler"
        data = json.loads(event["body"])
        print event

        if "callback_query" in data:
            return process_callback_query(data)

        # If it is replying to a message not sent by the chatbot, ignore it
        if "reply_to_message" in data["message"]:
            if data["message"]["reply_to_message"]["from"]["id"] != 910668396:
                print "not from chatbot"
                return {"statusCode": 200}

        sender_telegram_id = data["message"]["from"]["id"]
        chat_id = data["message"]["chat"]["id"]
        chat_type = data["message"]["chat"]["type"]
        source_message_id = data["message"]["message_id"]
        print data

        # Get list of approved IDs
        APPROVED_USER_LIST = map(long, APPROVED_USER_STR.split(", "))

        # Get telegram token handler
        # BASE_URL = "https://api.telegram.org/bot{}".format(TOKEN)
        reply_url = BASE_URL + "/sendMessage"

        # Check the telegram ID to see if user if approved
        if sender_telegram_id not in APPROVED_USER_LIST:
            if "get id" in str(data["message"]["text"]).lower():  # If message contains the string "get id"
                first_name = data["message"]["from"]["first_name"]  # Reply the user with his/her details
                response = "Your details are:{}".format('\n' + str(sender_telegram_id) + '\n' + str(first_name))
                data = {"text": response.encode("utf8"), "chat_id": sender_telegram_id}
                requests.post(reply_url, data)
            return {"statusCode": 200}

        response_string = ''

        message = data["message"]
        if "text" in message:
            if chat_type == "group" and str(message["text"]).lower() == "/hello":
                data = {"text": ("Hello I am Cheapo! Reply this message to talk to me!").encode("utf8"), "chat_id": chat_id, "reply_to_message_id": source_message_id}
                requests.post(reply_url, data)
            else:
                data1 = invoke_lambda_function("blankLambda", "RequestResponse", json.dumps(message["text"]))

                data = {"text": (str(data1)+" Text").encode("utf8"), "chat_id": chat_id, "reply_to_message_id": source_message_id}
                requests.post(reply_url, data)
                print "Lambda client invoked"
                print data1

        if "location" in message:
            json_response = invoke_lambda_function("queryGeoDatabase", "RequestResponse", json.dumps(message["location"]))

            # There is no filter for the initial result, hence is all possible sources
            sources_available, json_response = update_result_cache(json_response, SOURCE_DESC_NUM_MAP.values(),
                                                                   SOURCE_DESC_NUM_MAP.values(), chat_id,
                                                                   search_center_details=message["location"])
            json_response = paginate_results(json_response, 1)
            reply_or_edit_message_text(json_response, 1, sources_available, sources_available, chat_id, source_message_id, "REPLY")
            print "Lambda client invoked"

    except Exception as e:
        print "exception occured"
        print(str(e))

    return {"statusCode": 200}