import json
import logging
import boto3
from botocore.vendored import requests
from boto3.dynamodb.conditions import Key
import io
import sys
import os
import hashlib

from contextlib import closing
from ask_sdk_core.skill_builder import SkillBuilder
from ask_sdk_core.handler_input import HandlerInput
from ask_sdk_core.dispatch_components import (
    AbstractRequestHandler, AbstractExceptionHandler,
    AbstractResponseInterceptor, AbstractRequestInterceptor)
from ask_sdk_core.utils import is_intent_name, is_request_type, get_slot_value

"""
REVISION MADE: 3/9/2019 by Divya Vaidya
Added .set_should_end_session(False) to response_builder for all handle methods in the following
handlers: LaunchRequestHandler, HelpIntentHandler, SetLanguageIntentHandler, AskSetLanguageIntentHandler, 
FunTranslateIntentHandler, NoTargetLanguageIntentHandler and RepeatIntentHandler, 
to stop the skill from being exited prematurely.
"""

# Initialising clients and resources required for AWS products used within the application 
# as well as the required environment variables
# External products/APIs used:
# Fun Translate API: Used to translate the phrase into the chosen target language
# Amazon Polly: Text-to-speech synthesizer used to convert the translated phrase into a mp3 file
# Amazon S3: Used to store the audio files that have been translated
# DynamoDB: Used to store all previously translated phrases (alongside the language they have been translated to)
# DynamoDB (Cont'd): so that the phrases do not have to be translated over and over again
# The DynamoDB resource was used instead of the client so the .Table method could be used
polly = boto3.client('polly');
s3 = boto3.client('s3');
dynamoDB = boto3.resource('dynamodb');
bucketName = os.environ['ftbucket'];
table = dynamoDB.Table(os.environ['ftDB']);

# Skill Builder object
sb = SkillBuilder();

logger = logging.getLogger(__name__);
logger.setLevel(logging.INFO);


# Initialising dictionary containing the Polly voices to be used for text-to-speech synthesis for each relevant language
voices = {
            'dothraki': 'Zeina',
            'piglatin': 'Joey',
            'shakespeare': 'Brian'
         };


""" Handler used to launch skill and reply to initial skill prompt and reset the
    session attributed every time a new session is started
"""
class LaunchRequestHandler(AbstractRequestHandler):
    
    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        return is_request_type("LaunchRequest")(handler_input);
        
    def handle(self, handler_input):
        # type: (HandlerInput) -> Response
        
        # Handler simply responds to user and provides all information about the 
        # skill and what it can do
        logger.info("In LaunchRequestHandler");
        handler_input.attributes_manager.session_attributes = {}
        speech = ('Welcome to Fun Translate. Fun Translate will translate any sentence or phrase to your chosen target language. '
                  'Please first select a target language to set. You can choose from Dothraki, Pig Latin or Shakespeare. '
                  'For more information, please say "Help"'
                 );
        # reprompt = "What do you want to do?";
        handler_input.response_builder.speak(speech).set_should_end_session(False);
        return handler_input.response_builder.response;
                
""" Handler used when session is ended in order to exit skill
"""
class SessionEndedRequestHandler(AbstractRequestHandler):
    
    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        return is_request_type("SessionEndedRequest")(handler_input);
    
    def handle(self, handler_input):
        # type: (HandlerInput) -> Response
        logger.info("In SessionEndedRequestHandler");
        print("Session ended with reason: {}".format(
            handler_input.request_envelope));
        return handler_input.response_builder.response;

""" Handler used when user asks for help, to provide user with information about 
    the skill and what it can do
"""
class HelpIntentHandler(AbstractRequestHandler):

    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        return is_intent_name("AMAZON.HelpIntent")(handler_input);
        
    def handle(self, handler_input):
        # type: (HandlerInput) -> Response
        logger.info("In HelpIntentHandler");
        
        # All the information regarding the application is relayed back to the user 
        # e.g. how to ask what the target language is set to or how to ask Alexa to
        # repeat the translated phrase
        handler_input.response_builder.speak('Fun Translate can translate any phrase or sentence you say into your target translation language. '
                                             'You must first select a target language to translate to. You can choose from Dothraki, Pig Latin or Shakespeare.  '
                                             'To set your target language, please say "Set language to " and your preferred language. '
                                             'Once you have chosen a language, you can then say the phrase you want translated. For example, you can say: "How do you say Hello", '
                                             'or even ask Fun Translate to repeat the translated phrase by saying: "Please repeat the translation. '
                                             'To find out what you have set the language to, please ask me "What is the target language?". Please note that '
                                             'you can only translate 5 sentences or phrases in the space of an hour.').set_should_end_session(False);
                                      
        return handler_input.response_builder.response

""" Handler used when user invokes either cancel or stop intent and session is 
    subsequently ended
"""
class ExitIntentHandler(AbstractRequestHandler):
    
    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        return (is_intent_name("AMAZON.CancelIntent")(handler_input) or
                is_intent_name("AMAZON.StopIntent")(handler_input));
                
    def handle(self, handler_input):
        # type: (HandlerInput) -> Response
        logger.info("In ExitIntentHandler");
        handler_input.response_builder.speak("Goodbye!").set_should_end_session(True);
        return handler_input.response_builder.response;
        
    


""" Handler for setting chosen language option.
    The ''handle'' method will take the language the user has chosen and set the
    language chosen as a session attribute. A session attribute called state will
    then also be set to "Language Set" to facilitate a check in the FunTranslateIntentHandler
    before the translation can be done
"""
class SetLanguageIntentHandler(AbstractRequestHandler):
    
    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        return is_intent_name("SetLanguageIntent")(handler_input);
        
    def handle(self, handler_input):
        # type: (HandlerInput) -> Response
        
        logger.info("In SetLanguageIntentHandler");
        
        # Slot value set for the language slot in the interaction model is set as a session attribute
        # to allow it to be accessed later on in the session when phrases need to be translated to the
        # specific language.
        # The state is captured as a session attribute here to help with handling the checking of the set language 
        # and the translation request. The set language is then repeated back to the user for confirmation.
        languageOption = handler_input.request_envelope.request.intent.slots["language"].value;
        attr = handler_input.attributes_manager.session_attributes;
        # The language String is formatted so that it matches the format of the key values
        # in the voices dictionary above
        # The session attribute 'state' is set to Language Set so that it can be checked when the user 
        # attempts to translate a phrase before the language has been set. This check is used
        # in the "can_handle" method of both the FunTranslateIntentHandler and the NoTargetLanguageIntentHandler
        attr["language"] = languageOption.lower().replace(" ", "");
        attr["state"] = "Language Set";
        
        speech_text = ('Thank you for selecting your language. '
                       'Your language is now set to {} ').format(languageOption)
        
        reprompt_text = 'To find out what you have set the language to, please ask me "What is the target language?"'
        # Once the language has been set, the selected language is repeated back to the user
        return handler_input.response_builder.speak(speech_text).ask(reprompt_text).response
        

""" Handler used to check which language is currently set as the target translation language.
    If no language has been selected, then the user is asked to set the language.
"""
class AskSetLanguageIntentHandler(AbstractRequestHandler):
    
    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        return is_intent_name("AskSetLanguageIntent")(handler_input)
        
    def handle(self, handler_input):
        # type: (HandlerInput) -> Response
        
        # Gets the incoming session attributes that have been set within the session
        attr = handler_input.attributes_manager.session_attributes;
        
        # Checks whether the language has been set by checking the state session attribute.
        # If it has not been set, then this is relayed back to the user. If it has been set,
        # then the target language is stated back to the user.
        if attr == {}:
            outputSpeech = "No language has currently been set. Please set the language to continue";
        else:
            outputSpeech = "The language is currently set to {}".format(attr["language"]);
            
        return handler_input.response_builder.speak(outputSpeech).set_should_end_session(False).response;
  
""" Handler used to translate the phrase spoken by the user. The handler takes in the 
    captured phrase and utilises the utility functions below to first check if the 
    phrase has previously been translated and exists in the DynamoDB. If the phrase does not
    appear in the DynamoDB table, the function then translates the text by calling the API, 
    then uses AWS Polly's text-to-speech functionality to create the audio 
    clip. After this the audio is uploaded to the S3 bucket and then the audio is played back to
    the user. If there are any errors during any of the parts of the process, then an error is played
    back to the user instead.
"""      
class FunTranslateIntentHandler(AbstractRequestHandler):
    
    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        
        # Checks whether the right intent has been triggered and ensures language
        # has been set before the translation is handled
        attr = handler_input.attributes_manager.session_attributes
        return (is_intent_name("TranslateIntent")(handler_input) and
                attr.get("state") == "Language Set")
    
    def handle(self, handler_input):
        # type: (HandlerInput) -> Response
        
        # Initialising the necessary session attributes from previous requests that will
        # need to be utilised for the translation, in particular the sentence that needs 
        # to be translated and the language that has been set previously by the user
        # A String variable "key" is created by combining the sentence (stripped of whitespace)
        # and the selected language - this key is used as the key input for the DynamoDB table and
        # in the file path of the S3 object under which the audio file is saved.
        # A hash is also made of the key to be utilised later in the filepath of the S3 object
        logger.info("In FunTranslateIntentHandler");
        attr = handler_input.attributes_manager.session_attributes;
        selected_language = attr.get("language").lower().replace(" ", "");
        sentence = handler_input.request_envelope.request.intent.slots["sentence"].value;
        key = sentence.replace(" ","")+selected_language;
        md5 = (hashlib.md5(key.encode('utf-8'))).hexdigest();
        attr["last file key"] = key;
        
        # The dynamoDB is checked first to see if it contains the translation for the 
        # phrase that has been spoken and the target translation language. This is handled within
        # the queryDynamoDB function below
        table_query_bool = queryDynamoDB(key)
        
        # Checking whether the table has entries and whether the required translation has been found
        if table != {} and table_query_bool:
            
            # The table entry is then retrieved, as it contains the URL of the S3 bucket where the 
            # translation is stored and the audio is played back to the user from the S3 bucket's
            # URL. The entire process is wrapped in a try-catch block to avoid any errors that arise from
            # trying to access the methods from the boto3 resource used for DynamoDB
            try:
                tableEntry = table.get_item(
                        Key={
                            'OriginalPhraseandLanguage': key
                        }
                    );
                # As the "sentence" variable is formatted to match the dictionary entry,
                # the value for pig latin is formatted to include a whitespace so 
                # it can be replayed back to the user accurately.
                if selected_language == "piglatin":
                    selected_language = "pig latin"
                output = handler_input.response_builder.speak('The translation of the phrase {} in {} is: '.format(sentence, selected_language) + tableEntry['Item']['value']['url'] +
                                                                ' You can ask me to repeat the sentence by saying repeat, or ask me to translate something else. Remember, you can only translate 5 sentences in the space of an hour' ).set_should_end_session(False);
            except Exception as e:
                
                # Any exceptions are caught and relayed back to the user as an error
                logger.info("Could not access DynamoDB entry properly");
                output = handler_input.response_builder.speak("I am sorry, there was an error during translation");
        
        # If no entry is found in the DynamoDB table, then the phrase is translated from the start
        else:
            
            # The translateToTarget utility function is used to retrieve the translation of the input phrase
            translation = translateToTarget(sentence, selected_language, handler_input)
            logger.info(translation)
            
            # If any errors occured while getting the translation back from the API
            # then an error phrase is played back to the user or if the API limit 
            # is exceeded then the session is immediately ended as no further 
            # translations would be possible anyway
            if attr["translation_state"] == "Unauthorized":
                output = handler_input.response_builder.speak("I'm sorry, the sentence could not be translated. Please try saying something else")
            elif attr["translation_state"] == "Limit Exceeded":
                output = handler_input.response_builder.speak("I'm sorry, you can only translate 5 sentences or phrases in the space of an hour.".set_should_end_session(True))
            else:
                
                logger.info(selected_language)
                
                # The translated phrase is converted to speech using Amazon Polly and
                # the voice dictionary entry corresponding to the set language
                response = synthesizeSpeech(translation, voices[selected_language]);
                
                # A check is done to ensure that the audio file has been generated properly
                if (response != {}):
                    logger.info("Uploading Audio File to S3");
                    
                    # The audio file is then uploaded to the S3 bucket using the
                    # utility function putFileIntoS3Bucket, and the key, md5 hash
                    # and Audio Stream are used as parameters. Since the audio file 
                    # is received as a StreamingBody object, the read method is used
                    # so that the stream can be inputted as bytes and uploaded 
                    # properly to the S3 bucket.
                    file_upload_bool = putFileIntoS3Bucket(key, md5, response['AudioStream'].read());
                        
                    # Check to see if the file has been uploaded to the S3 bucket properly or not.
                    # If it has not been, the user is alerted about the error.
                    if file_upload_bool == True:
                        
                        # The url for the audio file is formatted in SSML according
                        # to the format of the S3 bucket's url so that it can be 
                        # embedded into Alexa's response and accessed  directly 
                        # during the speech response itself.
                        url = ' <audio src= "https://{}.s3.amazonaws.com/{}/{}/translated.mp3?region=eu-west-1"/> '.format(bucketName, md5, key);
                        logger.info(url)
                        
                        # As above, if the selected language is pig latin, then
                        # it is formatted so that it is spoken properly
                        if selected_language == "piglatin":
                            selected_language = "pig latin"
                        output = handler_input.response_builder.speak('The translation of the phrase {} in {} is: '.format(sentence, selected_language) + url +
                                                                        ' You can ask me to repeat the sentence by saying repeat, or ask me to translate something else. Remember, you can only translate 5 sentences in the space of an hour' ).set_should_end_session(False);
                        
                        # Once all the necessary translation steps are taken, then
                        # the key, translation and url are uploaded to the DynamoDB table
                        # using the utility function below.
                        uploadDetailsToDynamoDB(key, translation, url);
                            
                    else:
                            
                        output = handler_input.response_builder.speak("Sorry there was an issue uploading the file to the S3 bucket");
                else:
                            
                        output = handler_input.response_builder.speak("Uh-oh, the night is dark and full of errors");
                
        return output.response;
        
""" Handler used to catch case where user attempts to translate a phrase before 
    the language has been set by the user. The handler simply checked whether the 
    state attribute has been changed to "Language Set" and off the basis of this, 
    the handler provides a reply telling the user to set a language instead.
"""       
class NoTargetLanguageIntentHandler(AbstractRequestHandler):        
        
    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        
        # The state session attribute is checked to see if the language has not 
        # been set and if the user is attempting to translate a phrase before the
        # language has been set.
        attr = handler_input.attributes_manager.session_attributes
        return (is_intent_name("TranslateIntent")(handler_input) and
                (attr.get("state") != "Language Set" or (attr == {})))
    
    def handle(self, handler_input):
        # type: (HandlerInput) -> Response
        
        logger.info("In NoTargetLanguageIntentHandler");
        
        # Response is provided telling user to select a language before translating
        speech = ('Please select a target translation language before attempting '
                  'to translate a phrase. '
                  'You can select from Pig Latin, Dothraki and Shakespeare. Thank you.');
        return handler_input.response_builder.speak(speech).set_should_end_session(False).response;

""" Handler used to repeat the translated phrase back to the user, when they wish to hear
    it again. The handler uses the last file key session attribute logged when the phrase 
    is initially translated 
"""    
class RepeatIntentHandler(AbstractRequestHandler):
    
    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        
        # Checks if the user is asking for the repeat intent - additional sample
        # utterances have been added to invocation model to ensure all possible 
        # invocation cases are covered
        return is_intent_name("AMAZON.RepeatIntent")(handler_input);
    
    def handle(self, handler_input):
        # type: (HandlerInput) -> Response
        
        logger.info("In RepeatIntentHandler");
        
        # Receiving the session atributes for the current session to check if 
        # something has been translated previously
        attr = handler_input.attributes_manager.session_attributes;
        
        # Checks if whether any session attributes have been set or if specifically
        # the last file key session attribute has been set as this is what drives the
        # repitition of the phrase.
        if attr == {}:
            
            outputSpeech = ('Sorry, it seems as though you have not said anything before for me to repeat. '
                            'Please firstly say a phrase for me to translate.');
                            
        elif attr["last file key"] is None:
            
            outputSpeech = ('Sorry, it seems as though you have not said anything before for me to repeat. '
                            'Please firstly say a phrase for me to translate.');
        else:
            
            # Try-catch block catches any exceptions caused due to accessing the 
            # boto3 resource.
            try:
                # Based on the last key entered into the session attributes,
                # the previous entry is retrieved from the DynamoDB table and
                # the url of the received table entry is extracted so that the 
                # translated phrase alone can be repeated back to the user
                tableEntry = table.get_item(
                    Key={
                        'OriginalPhraseandLanguage': attr["last file key"]
                    }
                );
                logger.info(tableEntry)
                
                # The URL is retrieved from the table entry dictionary
                outputSpeech = tableEntry['Item']['value']['url'] 
                
                
            except Exception as e:
                logger.info("Could not access DynamoDB entry properly");
                outputSpeech = "I'm sorry, there was an error in attempting to repeat the phrase"
            
        # The phrase to repeat is played back to the user
        return handler_input.response_builder.speak(outputSpeech).set_should_end_session(False).response;
        
# Utility functions
""" Function used to make API call to translate the input phrase from English into
    set target language. Based on the language that has been set as the language option,
    the function will call the relevant API path and translate the phrase into the 
    target language. 
"""
def translateToTarget(input_phrase, language, handler_input):
    # type: (String, String, HandlerInput) -> String
    
    # The return variable is initialized and session attributes are received
    translation = "";
    attr = handler_input.attributes_manager.session_attributes;
    
    # The URL of the API is formatted to match the request format required to 
    # obtain the translated response from the API
    url = ('https://api.funtranslations.com/translate/'+
                language + 
                '.json?text=' + 
                input_phrase
                );
    
    # The process of obtaining the response from the API is wrapped in a try-catch
    # block to avoid any errors occuring while trying to obtain the reponse through
    # the requests.get method
    try:
        # Using the get method from the Python requests library to access the URL
        # The timeout limit for the get request is increased to 50 seconds as the 
        # default timeout limit is only 3 seconds
        translation_response = requests.get(url, timeout=50)
        
        # Response is checked to see if an error is received instead of the 
        # required translation response. The translation state attribute is set 
        # based on the exact status code. If the status code is 429, the API's call
        # limit has been exceeded as it is only possible to call the API 5 times in
        # the space of an hour. If the status code is 401, then there was an error
        # whilst accessing the API. Otherwise the required translation is extracted
        # from the dictionary that is received as a reponse from the API
        if translation_response.status_code == 429:
            attr["translation_state"] = "Limit Exceeded"
        elif translation_response.status_code == 401:
            attr["translation_state"] = "Unauthorized"
        else:
            
            # The String of the translated response is then extracted into a variable
            # The String is then manipulated to remove any extra information that 
            # is included within the response text itself, so that only the translated
            # text is left. Then the manipulated text is set as the return value.
            # Finally the translation state is set to translated so that it can be 
            # used in the fun translate handler
            txt = translation_response.text;
            x = txt.find("translated");
            y = txt.find("text");
            txt = txt[x:y];
            x = txt.find(":");
            y = txt.rfind(",");
            txt = txt[x+3:y-1];
            translation = txt;
            attr["translation_state"] = "Translated";
    
    # If any errors occur, then the error is simply logged into CloudWatch
    except Exception as e:
        logger.error(e);
    
    # The translated phrase is finally returned
    return translation;

""" Function used to convert the translated text into an audio file using functionality
    in AWS Polly. The out-of-the-box Polly function "synthesize_speech" is used to convert
    the SSML text into the required audio file with the  Polly voice defined for the language
    within the voices dictionary above
"""
def synthesizeSpeech(translated_text, voice):
    # type: (String, String) -> dict
    
    logger.info("In Synthesize Speech Method")
    # The response return value is initialized as an empty dictionary as the synthesize
    # speech method in Amazon Polly returns a dictionary containing the converted
    # audio file.
    response = {};
    
    # The translated text is embedded into an SSML format so that it can be spoken
    # properly by Alexa, with the correct effects. It is repeated twice, with a slower 
    # speaking voice the second time to allow the user to hear the translated text 
    # again.
    SSML = ('<speak><amazon:effect name="drc">'+
            translated_text + '</amazon:effect><prosody rate= "slow">' +
            '<amazon:effect name="drc"><p>' + translated_text +
            '</p></amazon:effect></prosody></speak>'
            );
    
    # This process of speech synthesis is wrapped in a try-catch block to catch
    # any client errors that may be caused by the Polly client.
    try:
        # The synthesize speech method from the Polly client is used to get back
        # the converted speech file. The input parameters indicate that the output
        # file should be in mp3 format, the audio fequency should be 22050Hz, the 
        # input text is in SSML format and the Polly voice to use should be the one
        # provided when the method is called.
        response = polly.synthesize_speech(OutputFormat = 'mp3',
                                SampleRate='22050',
                                Text = SSML,
                                TextType = 'ssml',
                                VoiceId = voice
                                );
    except Exception as e:
        logger.error(e);
    
    # The response dictionary is finally returned, and is used in the fun translate
    # handler
    return response;

""" Function used to upload the audio file into the S3 bucket for storage. It takes 
    in the String key which will be the combination of sentence to be translated and the 
    target language, as well as the md5 hashed value of the key to place the audio file 
    into the S3 bucket for easy access.
"""
def putFileIntoS3Bucket(key, hash_val, audio_stream):
    # type: (String, String) -> bool
    
    # The object key for the audio file so that it can be uniquely identified 
    # when the audio file is being retrieved.
    keyVal = "{}/{}/translated.mp3".format(hash_val, key)
    
    # Try-catch put in for same reason as above
    try:
        # The put object method is used here to place the audio file into the 
        # S3 bucket, by creating an S3 object. The access control list permission
        # for the file is set to 'public-read' so that the audio file can be accessed
        # by the handler when it must be played back to the user. The body is set 
        # as the audio stream that is passed to the method as a parameter, while the 
        # bucket is specified as the bucket instantiated in the environment
        # variables. The key is as formatted above.
        s3.put_object(ACL='public-read', Body= audio_stream, Bucket=bucketName, Key=keyVal);
        # The method returns true once the object is placed into the bucket.
        return True;
        
    except Exception as e:
        # Any exceptions are caught and logged and the method returns false if 
        # there are any issues.
        logger.error(e);
        return False;

""" Function used to upload the specified item into the DynamoDB table so that it
    can be accessed again if it has been previously translated. 
"""
def uploadDetailsToDynamoDB(key, translation, url):
    # type: (String, String, String) -> no return value
    
    # Surrounded by try-catch block to catch any errors caused by the DynamoDB resource
    try:
        
        # The item is put into the DynamoDB table with the combined sentence and
        # selected language as the key for the entry. These are mapped to the 
        # translation and the url for the audio file
        table.put_item(
            Item={
                'OriginalPhraseandLanguage': key,
                'value': {
                    'translation': translation,
                    'url': url
                }
            }
            
        )
        
    # Any caught exceptions are logged into CloudWatch 
    except Exception as e:
        logger.error(e);

""" Function used to check if dynamoDB has an entry for the sentence and target 
    language requested by the user in the current session. The function uses the 
    boto3 DynamoDB resource "query" function to check first if there are any 
    primary keys that match the required key. If there are any entries that match,
    then the function returns True as the phrase has been previously translated to 
    target language. Otherwise, the function returns False, if no match is found.
"""
def queryDynamoDB(key):
    # type: (String) -> bool
    
    # Surrounded by try-catch to avoid any errors that be caused by the boto3 resource
    try:
        
        # table is queried and produces a subtable containing all the matching keys
        # of the queried keys. This should only contain one entry as the table will not contain duplicate keys
        subtable = table.query(
                                KeyConditionExpression=Key('OriginalPhraseandLanguage').eq(key)
                             )
        logger.info(subtable)
        
        # If the entry required is found by the query function, then the Count will be 1
        # So the 'Count' entry in the subtable dictionary is checked to ensure whether
        # or not the entry has been found. The function then returns True as the translation has been found
        if subtable['Count'] != 0:
            return True
    except Exception as e:
        logger.error(e);
    
    # If the entry was not found or any other errors occured, then False is returned
    return False

# The handler for each Intent are added to the Skill Builder
sb.add_request_handler(LaunchRequestHandler());
sb.add_request_handler(SetLanguageIntentHandler());
sb.add_request_handler(AskSetLanguageIntentHandler());
sb.add_request_handler(FunTranslateIntentHandler());
sb.add_request_handler(NoTargetLanguageIntentHandler());
sb.add_request_handler(RepeatIntentHandler());
sb.add_request_handler(HelpIntentHandler());
sb.add_request_handler(ExitIntentHandler());
sb.add_request_handler(SessionEndedRequestHandler());


lambda_handler = sb.lambda_handler();
