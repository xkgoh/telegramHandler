import boto3
import os
import json

# Database configuration parameters
database_type = os.environ['AWS_DB_TYPE']  # Default = 'dynamodb'
database_region = os.environ['AWS_DB_REGION']  # Default = 'ap-southeast-1'
target_database_table = os.environ['TARGET_TABLE_NAME']  # Default = 'ResultCache'

def check_if_table_exists(target_database_table):
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
            TableName=target_database_table
        )

        # Wait for the table to exist before exiting
        print "Waiting for " + str(target_database_table) + " table to be created..."
        waiter = database_client.get_waiter('table_exists')
        waiter.wait(TableName=target_database_table)

        print target_database_table + " table created."
    except database_client.exceptions.ResourceInUseException:
        pass
    return


def get_from_result_cache(chat_id):
    database = boto3.resource(database_type, region_name=database_region)
    table = database.Table(target_database_table)

    response = table.get_item(
        Key={
            'ChatID': chat_id
        }
    )

    print "Retrieved Item from Result Cache."
    return response['Item']


# Input a list of merchants object to be written to the database
def write_to_results_cache(chat_id, json_response):

    check_if_table_exists(target_database_table)

    database = boto3.resource(database_type, region_name=database_region)
    table = database.Table(target_database_table)

    item = {
        'ChatID': int(chat_id),
        'Result': json.dumps(json_response)
    }

    response = table.put_item(Item=item)

    print "Successfully cached " + str(chat_id) + "'s details to " + str(database_type) + "-" + str(target_database_table) + "."
    return True


def remove_from_results_cache(chat_id):

    database = boto3.resource(database_type, region_name=database_region)
    table = database.Table(target_database_table)

    response = table.delete_item(
        Key={
            'ChatID': chat_id
        }
    )

    print("DeleteItem succeeded:")
    print(json.dumps(response))