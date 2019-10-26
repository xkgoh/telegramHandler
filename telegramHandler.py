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
RADIUS_CHANGE = 250  # Increasing or decreasing the radius changes it by 250 each time
MAX_SEARCH_RADIUS = 5000
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
def create_reply_keyboard_page_markup(current_page, max_page, cur_radius, sources_available):
    print "Current Page: " + str(current_page) + " Max Page:" + str(max_page)
    if max_page == 0:
        return {}

    page_number_buttons_arr = []
    radius_buttons_arr = []
    source_buttons_arr = []

    check_mark_emoji = u'\U00002705'  # check mark for filter
    cross_mark_emoji = u'\U0000274E'  # cross mark for cancel filter

    if current_page != max_page != 1:  # If there is only 1 page or no contents
        if 1 < current_page < max_page:
            page_number_buttons_arr.append(create_inline_keyboard_button("Page "+str(current_page-1), current_page-1))
            page_number_buttons_arr.append(create_inline_keyboard_button("Page "+str(current_page+1), current_page+1))
        elif current_page == 1:  # If first page
            page_number_buttons_arr.append(create_inline_keyboard_button("Page "+str(current_page+1), current_page+1))
        elif current_page == max_page:  # If last page
            page_number_buttons_arr.append(create_inline_keyboard_button("Page " + str(current_page - 1), current_page - 1))

    if len(sources_available) > 0:

        if cur_radius > RADIUS_CHANGE:
            radius_buttons_arr.append(create_inline_keyboard_button("- Radius", cur_radius-RADIUS_CHANGE))
        if cur_radius < MAX_SEARCH_RADIUS:
            radius_buttons_arr.append(create_inline_keyboard_button("+ Radius", cur_radius+RADIUS_CHANGE))

        if 1 in sources_available:
            source_buttons_arr.append(create_inline_keyboard_button(check_mark_emoji + " ENTR", "ENTR"))
        else:
            source_buttons_arr.append(create_inline_keyboard_button(cross_mark_emoji + " ENTR", "ENTR"))

        if 2 in sources_available:
            source_buttons_arr.append(create_inline_keyboard_button(check_mark_emoji + " CITI", "CITI"))
        else:
            source_buttons_arr.append(create_inline_keyboard_button(cross_mark_emoji + " CITI", "CITI"))

        if 3 in sources_available:
            source_buttons_arr.append(create_inline_keyboard_button(check_mark_emoji + " OCBC", "OCBC"))
        else:
            source_buttons_arr.append(create_inline_keyboard_button(cross_mark_emoji + " OCBC", "OCBC"))

    reply_markup = {"inline_keyboard": [page_number_buttons_arr, radius_buttons_arr, source_buttons_arr]}
    return reply_markup

def create_inline_keyboard_button(button_data, callback_data):
    return {"text": button_data, "callback_data": callback_data}

def update_source_filters(json_response, filter_value):
    json_response['sourceFilter'] = filter_value
    return json_response



def lambda_handler(event, context):
    try:
        print "Initializaing Handler"
        data = json.loads(event["body"])
        print event

        if "callback_query" in data:
            reply_url = BASE_URL + "/editMessageText"
            source_message_id = data["callback_query"]["message"]["message_id"]
            source_chat_id = data["callback_query"]["message"]["chat"]["id"]
            callback_query_data = data["callback_query"]["data"]

            cached_message = telegramHandlerDBWriter.get_from_result_cache(source_chat_id)
            cached_json_reply = json.loads(cached_message['Result'])
            data_sources = cached_json_reply['sourceFilter']
            search_center_details = {"latitude": cached_json_reply["searchCenterLatitude"],
                                     "longitude": cached_json_reply["searchCenterLongitude"]}

            if str(callback_query_data).isdigit():
                callback_query_data = int(callback_query_data)

                if callback_query_data >= 250:  # If it involves changes to the radius
                    search_radius = callback_query_data
                    print "SEARCH RADIUS CHANGE " + str(search_radius)
                    current_page = 1
                    # json_input = message["location"]
                    # json_input["searchRadius"] = 800
                    # reply_item = telegramHandlerDBWriter.get_from_result_cache(source_chat_id)
                    # cached_json_reply = json.loads(reply_item['Result'])
                    # print "RESULT IS "
                    # print cached_json_reply
                    # search_details = {}
                    # search_details['latitude'] = cached_json_reply['searchCenterLatitude']
                    # search_details['longitude'] = cached_json_reply['searchCenterLongitude']
                    search_center_details['searchRadius'] = int(search_radius)

                    # Execute another search with the new radius
                    json_response = invoke_lambda_function("queryGeoDatabase", "RequestResponse",
                                                           json.dumps(search_center_details))
                    json_response = filter_merchant_category(json_response, [1, 2, 3])
                    json_response = sort_results_by_distance(json_response, search_center_details)
                    json_response = update_source_filters(json_response, [1, 2, 3])
                    telegramHandlerDBWriter.write_to_results_cache(source_chat_id, json_response)

                else:  # If its moving to the next page
                    current_page = callback_query_data
                    json_response = cached_json_reply


            else:  # If filter of the data source
                callback_query_data = str(callback_query_data)

                if callback_query_data == "ENTR":
                    if 1 not in data_sources:
                        data_sources.append(1)
                    elif len(data_sources) > 1:
                        data_sources.remove(1)
                    else:
                        reply_url = BASE_URL + "/answerCallbackQuery"
                        callback_query_id = data["callback_query"]["id"]
                        reply_data = {"callback_query_id": callback_query_id}
                        requests.post(reply_url, reply_data)
                        print "executed callback query"
                        return {"statusCode": 200}

                if callback_query_data == "CITI":
                    if 2 not in data_sources:
                        data_sources.append(2)
                    elif len(data_sources) > 1:
                        data_sources.remove(2)
                    else:
                        reply_url = BASE_URL + "/answerCallbackQuery"
                        callback_query_id = data["callback_query"]["id"]
                        reply_data = {"callback_query_id": callback_query_id}
                        requests.post(reply_url, reply_data)
                        print "executed callback query"
                        return {"statusCode": 200}

                if callback_query_data == "OCBC":
                    if 3 not in data_sources:
                        data_sources.append(3)
                    elif len(data_sources) > 1:
                        data_sources.remove(3)
                    else:
                        reply_url = BASE_URL + "/answerCallbackQuery"
                        callback_query_id = data["callback_query"]["id"]
                        reply_data = {"callback_query_id": callback_query_id}
                        requests.post(reply_url, reply_data)
                        print "executed callback query"
                        return {"statusCode": 200}

                current_page = 1
                reply_item = telegramHandlerDBWriter.get_from_result_cache(source_chat_id)
                json_response = json.loads(reply_item['Result'])
                json_response = update_source_filters(json_response, data_sources)
                telegramHandlerDBWriter.write_to_results_cache(source_chat_id, json_response)  # Update the cache with the latest source filter

            print "Trying to paginate "
            print json_response

            json_response = filter_merchant_category(json_response, data_sources)
            json_response = sort_results_by_distance(json_response, search_center_details)

            json_response = paginate_results(json_response, current_page)
            # markdown_reply = format_json_response(json_response, message["location"], search_parameters['radius'],
            #                                       original_merchant_length)
            print "paginate "

            markdown_reply, sources_available = format_json_response(json_response)
            # print "mark down reply is"
            # print markdown_reply

            print "paginate 100"

            reply_markup = create_reply_keyboard_page_markup(current_page, int(math.ceil(float(json_response['totalItems'])/float(MAX_NUM_RESULTS_PER_PAGE))), int(json_response['searchRadius']), sources_available)

            print "paginate 200"

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
            # json_input = message["location"]
            # json_input["searchRadius"] = 800
            json_response = invoke_lambda_function("queryGeoDatabase", "RequestResponse", json.dumps(message["location"]))
            # json_response = invoke_lambda_function("queryGeoDatabase", "RequestResponse",
            #                                        json.dumps(json_input))
            print "Lambda client invoked"
            json_response = filter_merchant_category(json_response, [1, 2, 3])
            original_merchant_length = len(json_response['locations'])
            json_response = sort_results_by_distance(json_response, message["location"])
            json_response = update_source_filters(json_response, [1, 2, 3])
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
            markdown_reply, sources_available = format_json_response(json_response)

            # print markdown_reply
            print "sources availabel are " + str(sources_available)

            # reply_markup={"inline_keyboard":[[{"text": "Page 2", "callback_data": 2}]]}
            print "total item " + str(json_response['totalItems'])

            reply_markup = create_reply_keyboard_page_markup(1, int(
                math.ceil(float(json_response['totalItems']) / float(MAX_NUM_RESULTS_PER_PAGE))), int(json_response['searchRadius']), sources_available)

            data = {"text": markdown_reply.encode("utf8"), "chat_id": chat_id, "parse_mode": "markdown",
                    "reply_to_message_id": source_message_id, "reply_markup": json.dumps(reply_markup)}
            post_reply = requests.post(reply_url, data)
            print str(post_reply.text)
            print "Lambda client invoked"

    except Exception as e:
        print "exception occured"
        print(str(e))

    return {"statusCode": 200}