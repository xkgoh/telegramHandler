import boto3
import os
import json
import logging

# Database configuration parameters
database_type = os.environ['AWS_DB_TYPE']  # Default = 'dynamodb'
database_region = os.environ['AWS_DB_REGION']  # Default = 'ap-southeast-1'
cache_database_table = os.environ['CACHE_TABLE_NAME']  # Default = 'ResultCache'
user_database_table = os.environ['USER_TABLE_NAME']
logging_level = int(os.environ['LOGGING_LEVEL'])

logger = logging.getLogger()
logger.setLevel(logging_level)

def check_if_cache_table_exists():
    database_client = boto3.client(database_type)
    try:
        response = database_client.create_table(
            AttributeDefinitions=[
                {
                    'AttributeName': 'ChatID',
                    'AttributeType': 'N'
                }
            ],
            KeySchema=[
                {
                    'AttributeName': 'ChatID',
                    'KeyType': 'HASH'
                }
            ],
            ProvisionedThroughput={
                'ReadCapacityUnits': 5,
                'WriteCapacityUnits': 5
            },
            TableName=cache_database_table
        )

        # Wait for the table to exist before exiting
        logger.info("Waiting for " + str(cache_database_table) + " table to be created...")
        waiter = database_client.get_waiter('table_exists')
        waiter.wait(TableName=cache_database_table)

        logger.info(cache_database_table + " table created.")
    except database_client.exceptions.ResourceInUseException:
        pass
    return


def check_if_user_table_exists():
    database_client = boto3.client(database_type)
    try:
        response = database_client.create_table(
            AttributeDefinitions=[
                {
                    'AttributeName': 'TelegramID',
                    'AttributeType': 'N'
                }
            ],
            KeySchema=[
                {
                    'AttributeName': 'TelegramID',
                    'KeyType': 'HASH'
                }
            ],
            ProvisionedThroughput={
                'ReadCapacityUnits': 5,
                'WriteCapacityUnits': 5
            },
            TableName=user_database_table
        )

        # Wait for the table to exist before exiting
        logger.info("Waiting for " + str(user_database_table) + " table to be created...")
        waiter = database_client.get_waiter('table_exists')
        waiter.wait(TableName=user_database_table)

        logger.info(user_database_table + " table created.")
    except database_client.exceptions.ResourceInUseException:
        pass
    return


def get_from_result_cache(chat_id):
    database = boto3.resource(database_type, region_name=database_region)
    table = database.Table(cache_database_table)

    response = table.get_item(
        Key={
            'ChatID': chat_id
        }
    )

    logger.debug("Retrieved Item from Result Cache.")
    logger.debug(response['Item'])
    return response['Item']


def get_from_user_table(telegram_id):
    database = boto3.resource(database_type, region_name=database_region)
    table = database.Table(user_database_table)

    response = table.get_item(
        Key={
            'TelegramID': telegram_id
        }
    )

    if "Item" in response:
        logger.debug("Retrieved Item from User Table.")
        logger.debug(response['Item'])
        return response['Item']
    else:
        logger.info(str(telegram_id) + " not found in user table.")
        return None


# Input a list of merchants object to be written to the database
def write_to_results_cache(chat_id, json_response):

    # check_if_cache_table_exists()

    database = boto3.resource(database_type, region_name=database_region)
    table = database.Table(cache_database_table)

    item = {
        'ChatID': int(chat_id),
        'Result': json.dumps(json_response)
    }

    response = table.put_item(Item=item)

    logger.debug("Successfully cached " + str(chat_id) + "'s details to " + str(database_type) + "-" + str(cache_database_table) + ".")
    return True


# Input a list of merchants object to be written to the database
def write_to_user_table(telegram_id, name):

    # check_if_user_table_exists()

    database = boto3.resource(database_type, region_name=database_region)
    table = database.Table(user_database_table)

    item = {
        'TelegramID': int(telegram_id),
        'UserName': name
    }

    response = table.put_item(Item=item)

    logger.debug("Successfully wrote " + str(telegram_id) + " " + name + "'s details to " + str(database_type) + "-" + str(user_database_table) + ".")
    return True


def remove_from_results_cache(chat_id):

    database = boto3.resource(database_type, region_name=database_region)
    table = database.Table(cache_database_table)

    response = table.delete_item(
        Key={
            'ChatID': chat_id
        }
    )

    logger.debug("Removed " + str(chat_id) + "'s results from cache")
    logger.debug(json.dumps(response))
    return True