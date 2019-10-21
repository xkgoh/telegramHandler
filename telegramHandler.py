import boto3
import requests
import json
import os
import sys
import math
import re

import telegramHandlerDBWriter
from telegramHandlerHelper import sort_results_by_distance, filter_merchant_category, paginate_results, format_json_response


RADIUS_CHANGE_FACTOR = 0.65  # 85% change
MAX_NUM_RESULTS_PER_PAGE = 20
APPROVED_USER_STR = os.environ['APPROVED_USER_LIST']
TOKEN = os.environ['TELEGRAM_BOT_TOKEN']
BASE_URL = "https://api.telegram.org/bot{}".format(TOKEN)













# Invoke a lambda function and returns the json data returned
def invoke_lambda_function(function_name, invocation_type, payload_string):
    lambda_client = boto3.client('lambda')
    invoke_response = lambda_client.invoke(FunctionName=function_name,
                                           InvocationType=invocation_type,
                                           Payload=payload_string)
    return json.loads(invoke_response['Payload'].read())


# Create the reply markup keyboard based on the page number
def create_reply_keyboard_page_markup(current_page, max_page):
    print "Current Page: " + str(current_page) + " Max Page:" + str(max_page)
    if current_page == max_page == 1 or max_page == 0:  # If there is only 1 page
        return {}
    reply_markup = {}
    if 1 < current_page < max_page:
        reply_markup = {"inline_keyboard": [[{"text": "Page " + str(current_page - 1), "callback_data": current_page - 1}, {"text": "Page " + str(current_page + 1), "callback_data": current_page + 1}]]}
    elif current_page == 1:  # If first page
        # reply_markup = {"inline_keyboard": [[{"text": "Page " + str(current_page + 1), "callback_data": current_page + 1}]]}
        reply_markup = {"inline_keyboard": [[create_inline_keyboard_button("Page "+str(current_page+1), current_page+1)]]}
    elif current_page == max_page:  # If last page
        reply_markup = {"inline_keyboard": [[{"text": "Page " + str(current_page - 1), "callback_data": current_page - 1}]]}
    return reply_markup

def create_inline_keyboard_button(button_data, callback_data):
    return {"text": button_data, "callback_data": callback_data}


def lambda_handler(event, context):
    try:
        print "Initializaing Handler"
        data = json.loads(event["body"])
        print event

        if "callback_query" in data:
            reply_url = BASE_URL + "/editMessageText"
            source_message_id = data["callback_query"]["message"]["message_id"]
            source_chat_id = data["callback_query"]["message"]["chat"]["id"]
            current_page = int(data["callback_query"]["data"])
            reply_item = telegramHandlerDBWriter.get_from_result_cache(source_chat_id)
            print "reply is"
            print reply_item
            json_response = paginate_results(json.loads(reply_item['Result']), current_page)
            # markdown_reply = format_json_response(json_response, message["location"], search_parameters['radius'],
            #                                       original_merchant_length)
            print "paginate "
            markdown_reply = format_json_response(json_response)
            print "mark down reply is"
            print markdown_reply

            reply_markup = create_reply_keyboard_page_markup(current_page, int(math.ceil(float(json_response['totalItems'])/float(MAX_NUM_RESULTS_PER_PAGE))))
            reply_data = {"chat_id": source_chat_id, "message_id": source_message_id, "text": markdown_reply.encode("utf8"), "parse_mode": "markdown", "reply_markup": json.dumps(reply_markup)}
            post_reply = requests.post(reply_url, reply_data)
            print str(post_reply.text)
            print "executing call back query"
            reply_url = BASE_URL + "/answerCallbackQuery"
            callback_query_id = data["callback_query"]["id"]
            reply_data = {"callback_query_id": callback_query_id}
            requests.post(reply_url, reply_data)
            print "executed callback query"
            return {"statusCode": 200}

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
            print "Lambda client invoked"
            json_response = filter_merchant_category(json_response)
            original_merchant_length = len(json_response['locations'])
            json_response = sort_results_by_distance(json_response, message["location"])
            telegramHandlerDBWriter.write_to_results_cache(chat_id, json_response)
            json_response = paginate_results(json_response, 1)

            # if len(json_response['locations']) > MAX_NUM_RESULTS_PER_PAGE:
            #     print ""
            #     # paginate_results



            # num_locations_returned = len(json_response['locations'])
            # print "before reducing radius is " + str(num_locations_returned)
            #
            search_parameters = message['location']
            search_parameters['radius'] = int(json_response['searchRadius'])
            #
            # while num_locations_returned > MAX_NUM_RESULTS_RETURNED:
            #     # Reduce the search radius
            #     search_parameters = message['location']
            #     estimated_radius = int(float(MAX_NUM_RESULTS_RETURNED)/float(num_locations_returned)*float(json_response['searchRadius']))
            #     radius_change = int(json_response['searchRadius']) - estimated_radius
            #     search_parameters['radius'] = int(json_response['searchRadius']) - int(math.floor(radius_change*RADIUS_CHANGE_FACTOR))
            #     print search_parameters
            #     invoke_response = lambda_client.invoke(FunctionName="queryGeoDatabase",
            #                                            InvocationType='RequestResponse',
            #                                            Payload=json.dumps(search_parameters))
            #     json_response = json.loads(invoke_response['Payload'].read())
            #     json_response = filter_merchant_category(json_response)
            #     num_locations_returned = len(json_response['locations'])
            #     print "Search radius " + str(search_parameters['radius']) + " results: " + str(num_locations_returned)



            # json_response = invoke_response['Payload'].read()
            # print "after reducing radius is " + str(len(json_response['locations']))
            # markdown_reply = format_json_response(json_response, message["location"], search_parameters['radius'], original_merchant_length)
            markdown_reply = format_json_response(json_response)

            # print markdown_reply
            print "size of markdown reply" + str(sys.getsizeof(markdown_reply))

            # reply_markup={"inline_keyboard":[[{"text": "Page 2", "callback_data": 2}]]}
            print "total item " + str(json_response['totalItems'])

            reply_markup = create_reply_keyboard_page_markup(1, int(
                math.ceil(float(json_response['totalItems']) / float(MAX_NUM_RESULTS_PER_PAGE))))

            data = {"text": markdown_reply.encode("utf8"), "chat_id": chat_id, "parse_mode": "markdown",
                    "reply_to_message_id": source_message_id, "reply_markup": json.dumps(reply_markup)}
            post_reply = requests.post(reply_url, data)
            print str(post_reply.text)
            print "Lambda client invoked"

    except Exception as e:
        print "exception occured"
        print(str(e))

    return {"statusCode": 200}