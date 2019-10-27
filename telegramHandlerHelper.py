from geopy.distance import geodesic
import json
import re

APPROVED_CATEGORIES = [1]
MAX_NUM_RESULTS_PER_PAGE = 20  # Max permited is 26, the number of letters in the alphabets
RADIUS_CHANGE = 250  # Increasing or decreasing the radius changes it by 250 each time
MAX_SEARCH_RADIUS = 5000
SOURCE_DESC_NUM_MAP = {"ENTR": 1, "CITI": 2, "OCBC": 3}
SOURCE_NUM_DESC_MAP = {1: "ENTR", 2: "CITI", 3: "OCBC"}
SOURCE_NUM_FULLDESC_MAP = {1: "Entertainer", 2: "Citi", 3: "OCBC"}


# A. Distance Related Methods #########


# Compute the distance between two pairs of coordinates
def compute_distance(latitude_A, longitude_A, latitude_B, longitude_B):
    location_A = (latitude_A, longitude_A)
    location_B = (latitude_B, longitude_B)
    return geodesic(location_A, location_B).meters


# Filter merchant details based on the top_N closest merchant from the center
def sort_results_by_distance(json_response, center_lat_lng):
    print "Executing sorting by distance"
    json_result = {'searchRadius': json_response['searchRadius'],
                    'searchCenterLatitude': center_lat_lng['latitude'],
                    'searchCenterLongitude': center_lat_lng['longitude']}
    json_location_sorted_arr = []
    location_temp_arr = []
    center_latitude, center_longitude = center_lat_lng['latitude'], center_lat_lng['longitude']

    # Compute the distance for each merchant and update the merchant json information with the distance
    for merchant in json_response['locations']:
        coordinates = json.loads(str(merchant['geoJson']['S']))
        latitude, longitude = coordinates['coordinates'][1], coordinates['coordinates'][0]
        distance = compute_distance(latitude, longitude, center_latitude, center_longitude)
        merchant['stadinceFromCenter'] = distance
        location_temp_arr.append((distance, merchant))
    location_temp_arr.sort(key=lambda tup: tup[0])  # Sort the merchants by distance

    # Add the sorted merchant list back into the array
    for i in range(len(location_temp_arr)):
        json_location_sorted_arr.append(location_temp_arr[i][1])

    json_result['locations'] = json_location_sorted_arr
    return json_result


# B. Filter Related Methods #########

# Filter the merchant categories to that listed in the APPROVED_CATEGORY variable, and return the merchant sources that contains it
def filter_merchant_source_and_category(json_response, sources_filter=None):  # Optional parameter that further filter by sources
    json_result = {'searchRadius': json_response['searchRadius']}
    json_location_filtered_arr = []
    sources_available = set()

    for merchant in json_response['locations']:
        merchant_category = int(merchant['Type']['N'])
        data_source_num = int(merchant['Source']['N'])
        # if merchant_category in APPROVED_CATEGORIES and data_source_num in data_sources:
        if merchant_category in APPROVED_CATEGORIES:
            if sources_filter is None or data_source_num in sources_filter:
                json_location_filtered_arr.append(merchant)
                sources_available.add(data_source_num)

    json_result['locations'] = json_location_filtered_arr
    return json_result, list(sources_available)


# Obtain the results for a given page number from the entire result set
def paginate_results(json_response, page_number):
    print "Paginating results."
    # print json_response
    # print type(json_response)
    json_result = {'searchRadius': json_response['searchRadius'],
                    'searchCenterLatitude': json_response['searchCenterLatitude'],
                    'searchCenterLongitude': json_response['searchCenterLongitude']}
    json_location_temp_arr = []

    start_index = min((page_number-1)*MAX_NUM_RESULTS_PER_PAGE, len(json_response['locations']))  # Index starts from 0
    end_index = min(page_number*MAX_NUM_RESULTS_PER_PAGE, len(json_response['locations']))  # Index ends at length-1

    if (start_index == end_index and start_index == len(json_response['locations'])):
        json_result['locations'] = []
        json_result['totalItems'] = 0
        print "No contents for this page"
    else:
        for i in range(start_index, end_index):
            json_location_temp_arr.append(json_response['locations'][i])
        json_result['locations'] = json_location_temp_arr
        json_result['startItemNumber'] = start_index + 1
        json_result['endItemNumber'] = end_index
        json_result['totalItems'] = len(json_response['locations'])
        print "Paginating completed."
    print json_result
    return json_result


# C. JSON Formatting Related Method

# Summarize offer details
def condense_offer_description(text):
    if re.search("SGD\d+ return voucher", text) is not None:
        text = re.search("SGD\d+ return voucher", text).group()
        text = text.replace('SGD', '$', 1).replace('return ', '', 1).strip()
        return text.strip()
    if re.search("\d+% off", text) is not None:
        text = re.search("\d+% off", text).group()
        return text.strip()
    if re.search("SGD\d+ off", text) is not None:
        text = re.search("SGD\d+ off", text).group().replace('SGD', '$', 1). strip()
    return text.strip()


# Convert a json_reply from dynamodb into a telegram markdown reply
def format_json_response(json_response):
    if json_response is None or len(json_response['locations']) == 0:
        print "Sorry, there are no results :("
        return "Sorry, there are no results :("

    locations = json_response

    # Format the onemap_url with the centerpoint
    onemap_url = "https://developers.onemap.sg/commonapi/staticmap/getStaticImage?layerchosen=default&lat=" \
                 + str(json_response['searchCenterLatitude']) + "&lng=" + str(json_response['searchCenterLongitude']) + "&zoom=15&height=512&width=512&points=[" \
                 + str(json_response['searchCenterLatitude']) + "," + str(json_response['searchCenterLongitude']) + ",%22255,0,0%22]"

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
        output_string = output_string + "*" + counter + ". " + str(location['Name']['S']) + "* ["+ location_emoji + "](http://maps.google.com/maps?q=loc:" + str(latitude) + "," + str(longitude) + ")"

        data_source = int(location['Source']['N'])
        additional_details = json.loads(str(location['AdditionalDetails']['S']))

        # Print the data source
        output_string = output_string + "[(" + SOURCE_NUM_FULLDESC_MAP.get(data_source) + ")](" + str(additional_details['SourceWebsite']) + ")"

        # Print additional info about discount/deal
        if additional_details.get('OfferDetails') and len(str(additional_details['OfferDetails'])) < 100:
            output_string = output_string + " - " + condense_offer_description(str(additional_details['OfferDetails']))
        output_string = output_string + "\n"
        # if counter == 'Z':
        #     counter = 'a'
        # if counter == 'z':
        #     break
        counter = chr(ord(counter)+1) # Increment to the next alphabet

    # Add in the onemap_url
    output_string = "*Cheapo found*[ ](" + onemap_url + ")*" + str(json_response['totalItems']) + " results in a " + str(json_response['searchRadius']) + "m radius!*\nDisplaying results " + str(json_response['startItemNumber']) + " to " + str(json_response['endItemNumber']) + "\n\n" + output_string
    return output_string #, list(sources_available)


# D. Keyboard Formatting Related Methods

# Create the reply markup keyboard based on the page number
def create_reply_keyboard_page_markup(current_page, max_page, cur_radius, sources_filter, sources_available):
    print "Current Page: " + str(current_page) + " Max Page:" + str(max_page)
    if max_page == 0:
        return {}

    page_number_buttons_arr, radius_buttons_arr, source_filter_buttons_arr = [], [], []

    check_mark_emoji = u'\U00002705'  # check mark for filter
    cross_mark_emoji = u'\U0000274E'  # cross mark for cancel filter
    red_cross_mark_emoji = u'\U0000274C'  # RED cross mark for result not available

    if not current_page == max_page == 1:  # If there is not only 1 page, print page buttons
        if 1 < current_page < max_page:
            page_number_buttons_arr.append(create_inline_keyboard_button("Page "+str(current_page-1), current_page-1))
            page_number_buttons_arr.append(create_inline_keyboard_button("Page "+str(current_page+1), current_page+1))
        elif current_page == 1:  # If first page
            page_number_buttons_arr.append(create_inline_keyboard_button("Page "+str(current_page+1), current_page+1))
        elif current_page == max_page:  # If last page
            page_number_buttons_arr.append(create_inline_keyboard_button("Page " + str(current_page - 1), current_page - 1))

    if (len(sources_filter) and len(sources_available)) > 0:  # If there are sources available for filter, print it

        if cur_radius > RADIUS_CHANGE:
            radius_buttons_arr.append(create_inline_keyboard_button("- Radius", cur_radius-RADIUS_CHANGE))
        if cur_radius < MAX_SEARCH_RADIUS:
            radius_buttons_arr.append(create_inline_keyboard_button("+ Radius", cur_radius+RADIUS_CHANGE))

        for x in range(1, 4):
            if x not in sources_available:
                emoji_selected, description_selected = red_cross_mark_emoji, "NIL"
            elif x in sources_filter:
                emoji_selected, description_selected = check_mark_emoji, SOURCE_NUM_DESC_MAP.get(x)
            else:
                emoji_selected, description_selected = cross_mark_emoji, SOURCE_NUM_DESC_MAP.get(x)

            source_filter_buttons_arr.append(create_inline_keyboard_button(emoji_selected + " " + SOURCE_NUM_DESC_MAP.get(x), description_selected))

    reply_markup = {"inline_keyboard": [page_number_buttons_arr, radius_buttons_arr, source_filter_buttons_arr]}
    return reply_markup


def create_inline_keyboard_button(button_data, callback_data):
    return {"text": button_data, "callback_data": callback_data}