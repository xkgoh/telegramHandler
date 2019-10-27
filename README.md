# telegramHandler

This folder contains the source code for the Cheapo! Telegram bot (@Cheapo_bot). Cheapo! is a telegram bot that returns the nearby deals given a location.

The folder contains the following pieces of code:
1. telegramHandler.py - Contains the main function where the execution begins
2. telegramHandlerHelper.py - Contains many helper methods (e.g. formatting, data cleaning, calculation rules) to support the main function
3. telegramHandlerDBWriter - Handles the interfacing betwen the lambda function and DynamoDB
