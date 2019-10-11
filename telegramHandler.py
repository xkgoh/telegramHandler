import boto3
import requests
import json
import os
import sys
import math
from geopy.distance import geodesic

MAX_NUM_RESULTS_RETURNED = 30
RADIUS_CHANGE_FACTOR = 0.65  # 85% change
APPROVED_CATEGORIES = [1]
APPROVED_USER_STR = os.environ['APPROVED_USER_LIST']
TOKEN = os.environ['TELEGRAM_BOT_TOKEN']


def compute_distance(latitude_A, longitude_A, latitude_B, longitude_B):
    location_A = (latitude_A, longitude_A)
    location_B = (latitude_B, longitude_B)
    return geodesic(location_A, location_B).meters


# Filter merchant details based on the top_N closest merchant from the center
def filter_merchant_top_N(json_response, center_lat_lng, top_N):
    print "EXECUTING TOP N"
    json_cleaned = {'searchRadius': json_response['searchRadius']}
    json_location_cleaned_arr = []
    location_temp_arr = []
    center_latitude, center_longitude = center_lat_lng['latitude'], center_lat_lng['longitude']

    # Compute the distance for each merchant
    for merchant in json_response['locations']:
        coordinates = json.loads(str(merchant['geoJson']['S']))
        latitude, longitude = coordinates['coordinates'][1], coordinates['coordinates'][0]
        distance = compute_distance(latitude, longitude, center_latitude, center_longitude)
        location_temp_arr.append((distance, merchant))
    location_temp_arr.sort(key=lambda tup: tup[0])
    print location_temp_arr

    # Add the sorted merchant list back into the array
    for i in range(min(MAX_NUM_RESULTS_RETURNED, len(location_temp_arr))):
        json_location_cleaned_arr.append(location_temp_arr[i][1])
        if i == min(MAX_NUM_RESULTS_RETURNED, len(location_temp_arr))-1:
            json_cleaned['searchRadius'] = location_temp_arr[i][0]

    json_cleaned['locations'] = json_location_cleaned_arr
    print json_cleaned
    return json_cleaned


def filter_merchant_category(json_response):
    json_cleaned = {'searchRadius': json_response['searchRadius']}
    json_location_cleaned_arr = []

    for merchant in json_response['locations']:
        merchant_category = int(merchant['Type']['N'])
        if merchant_category in APPROVED_CATEGORIES:
            json_location_cleaned_arr.append(merchant)
    json_cleaned['locations'] = json_location_cleaned_arr
    print "after cleaning"
    print json_cleaned
    return json_cleaned


# Convert a json_reply from dynamodb into a telegram markdown reply
def format_json_response(json_response, center, radius, original_merchant_length):
    if json_response is None:
        return "Sorry there are no results :("
    # locations = json.loads(json_response)
    locations = json_response
    print locations['locations']
    if len(locations['locations']) == 0:
        return "Sorry there are no results :("

    # Format the onemap_url with the centerpoint
    onemap_url = "https://developers.onemap.sg/commonapi/staticmap/getStaticImage?layerchosen=default&lat=" \
                 + str(center['latitude']) + "&lng=" + str(center['longitude']) + "&zoom=15&height=512&width=512&points=[" \
                 + str(center['latitude']) + "," + str(center['longitude']) + ",%22255,0,0%22]"

    output_string = ""
    counter = 'A'
    marker_colour = "144,238,144"  # Light green colour
    location_emoji = u'\U0001F4CD'  # Location pin

    for location in locations['locations']:

        # Insert the coordinate of the current merchant into the onemap_url
        coordinates = json.loads(str(location['geoJson']['S']))
        longitude = coordinates['coordinates'][0]
        latitude = coordinates['coordinates'][1]
        onemap_url = onemap_url + "|[" + str(latitude) + "," + str(longitude) + ",%22" + marker_colour + "%22,%22" + counter + "%22]"

        # Output the remaining details
        output_string = output_string + "***" + counter + ". " + str(location['Name']['S']) + "*** ["+ location_emoji + "](http://maps.google.com/maps?q=loc:" + str(latitude) + "," + str(longitude) + ") "

        data_source = int(location['Source']['N'])
        additional_details = json.loads(str(location['AdditionalDetails']['S']))

        # Print the data source
        if data_source == 1:
            output_string = output_string + "[(The Entertainer)](" + str(additional_details['SourceWebsite']) + ")"
        elif data_source == 2:
            output_string = output_string + "[(Citibank)](" + str(additional_details['SourceWebsite']) + ")"

        # Print additional info about discount/deal
        if additional_details.get('OfferDetails') and len(str(additional_details['OfferDetails'])) < 100:
            output_string = output_string + "\n" + str(additional_details['OfferDetails'])
        output_string = output_string + "\n\n"
        if counter == 'Z':
            counter = 'a'
        if counter == 'z':
            break
        counter = chr(ord(counter)+1) # Increment to the next alphabet

    # Add in the onemap_url
    if original_merchant_length != len(locations['locations']):
        output_string = "*Cheapo found*[ ](" + onemap_url + ")*" + str(original_merchant_length) + " results in a 1000m radius!*\nShowing top " + str(len(locations['locations'])) + " results within " + str(radius) + "m...\n\n" + output_string
    else:
        output_string = "*Cheapo found*[ ](" + onemap_url + ")*" + str(len(locations['locations'])) + " results in a " + str(radius) + "m radius!*\n\n" + output_string
    # print output_string
    return output_string


def lambda_handler(event, context):
    try:
        print "Initializaing Handler"

        data = json.loads(event["body"])

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
        BASE_URL = "https://api.telegram.org/bot{}".format(TOKEN)
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
                lambda_client = boto3.client('lambda')
                invoke_response = lambda_client.invoke(FunctionName="blankLambda",
                                                       InvocationType='RequestResponse',
                                                       Payload=json.dumps(message["text"])
                                                       )
                data1 = invoke_response['Payload'].read()
                data = {"text": (str(data1)+" Text").encode("utf8"), "chat_id": chat_id, "reply_to_message_id": source_message_id}
                requests.post(reply_url, data)
                print "Lambda client invoked"
                print data1

        if "location" in message:
            print "Coordinates received."
            lambda_client = boto3.client('lambda')
            invoke_response = lambda_client.invoke(FunctionName="queryGeoDatabase",
                                                   InvocationType='RequestResponse',
                                                   Payload=json.dumps(message["location"]))
            print "Lambda client invoked"
            json_response = json.loads(invoke_response['Payload'].read())
            json_response = filter_merchant_category(json_response)
            original_merchant_length = len(json_response['locations'])
            if len(json_response['locations']) > MAX_NUM_RESULTS_RETURNED:
                json_response = filter_merchant_top_N(json_response, message["location"], MAX_NUM_RESULTS_RETURNED)



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
            print "after reducing radius is " + str(len(json_response['locations']))
            markdown_reply = format_json_response(json_response, message["location"], search_parameters['radius'], original_merchant_length)
            # print markdown_reply
            print "size of markdown reply" + str(sys.getsizeof(markdown_reply))
            # data = {"text": markdown_reply.encode("utf8"), "chat_id": chat_id, "parse_mode": "markdown", "disable_web_page_preview": True}
            data = {"text": markdown_reply.encode("utf8"), "chat_id": chat_id, "parse_mode": "markdown", "reply_to_message_id": source_message_id}
            post_reply = requests.post(reply_url, data)
            print str(post_reply.text)
            print "Lambda client invoked"

    except Exception as e:
        print "exception occured"
        print(str(e))

    return {"statusCode": 200}