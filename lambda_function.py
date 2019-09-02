import json
import logging
import boto3
from botocore.vendored import requests
# import asyncio
import os
import hashlib

from contextlib import closing
from ask_sdk_core.skill_builder import SkillBuilder
from ask_sdk_core.handler_input import HandlerInput
from ask_sdk_core.dispatch_components import (
    AbstractRequestHandler, AbstractExceptionHandler,
    AbstractResponseInterceptor, AbstractRequestInterceptor)
from ask_sdk_core.utils import is_intent_name, is_request_type, get_slot_value


# Initialising clients required for AWS products used within the application 
# as well as the required environment variables
polly = boto3.client('polly');
s3 = boto3.client('s3');
dynamoDB = boto3.client("dynamodb");
bucketName = os.environ['ftbucket'];
table = dynamoDB.Table(os.environ['ftDB']);

# Skill Builder object
sb = SkillBuilder();

logger = logging.getLogger(__name__);
logger.setLevel(logging.INFO);


# Initialising dictionary containing the Polly voices to be used for text-to-speech synthesis for each relevant language
voices = {
            dothraki: 'Zeina',
            piglatin: 'Joey',
            shakespeare: 'Brian'
         };

""" Things to consider:
        Need to generate Access Key ID and Secret Access Key ????
"""

""" Handler used to launch skill and reply to initial skill prompt
"""
class LaunchRequestHandler(AbstractRequestHandler):
    
    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        return is_request_type("LaunchRequest")(handler_input);
        
    def handle(self, handler_input):
        # type: (HandlerInput) -> Response
        logger.info("In LaunchRequestHandler");
        
        speech = ('Welcome to Fun Translate. Fun Translate will translate any sentence or phrase to your chosen target language. '
                  'Please first select a target language to set. You can choose from Dothraki, Pig Latin or Shakespeare '
                  'For more information, please say "Help"'
                 );
        reprompt = "What do you want to do?";
        handler_input.response_builder.speak(speech).ask(reprompt);
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
        handler_input.response_builder.speak('Fun Translate can translate any phrase or sentence you say into your target translation language '
                                             'You must first select a target language to translate to. You can choose from Dothraki, Pig Latin or Shakespeare  '
                                             'Once you have chosen a language, you can then say the phrase you want translated. For example, you can say: "How do you say Hello" '
                                             'and even ask Fun Translate to repeat the translated phrase by saying, for example: "Please repeat the translation. '
                                             'To find out what you have set the language to, please ask me "What is the target language?". Please note that'
                                             'you can only translate 5 sentences or phrases in the space of an hour.').ask('What do you want to');
                                      
        return handler_input.response_builder.response

""" Handler used when user invokes either cancel or stop intent and session is 
    subsequently ended
"""
class ExitIntentHandler(AbstractRequestHandler):
    
    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        return (is_intent_name("AMAZON.CancelIntent")(handler_input) or
                is_intent_name("AMAZON.StopIntent"));
    def handle(self, handler_input):
        # type: (HandlerInput) -> Response
        logger.info("In ExitIntentHandler");
        handler_input.response_builder.speak(data.EXIT_SKILL_MESSAGE.set_should_end_session(True));
        return handler_input.response_builder.response;
        
    


# NEED TO CHECK FUNCTION TO CONSIDER DIALOG MODEL !!!!
""" Handler for setting chosen language option.
    The ''handle'' method will take the language the user has chosen and set the
    language chosen as a session attribute. A session attribute called state will
    then also be set to "Language Set" to facilitate a check in the FunTranslateIntentHandler
    before the translation can be done
"""
class SetLanguageIntentHandler(AbstractRequestHandler):
    
    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        # checks whether the dialogue is completed and the language slot has been filled before the
        # intent is handled
        return is_intent_name("SetLanguageIntent")(handler_input) and get_dialog_state(
            handler_input=handler_input) == DialogState.COMPLETED;
        
    def handle(self, handler_input):
        # type: (HandlerInput) -> Response
        
        logger.info("In SetLanguageIntentHandler")(handler_input);
        
        # Slot value set for the language slot in the interaction model is set as a session attribute
        # to allow it to be accessed later on in the session when phrases need to be translated to the
        # specific language. No null check is used here as interaction model includes dialog model and
        # dialog delegation to ensure slot is filled beforehand.
        # The state is captured as a session attribute here to help with handling the checking of the set language 
        # and the translation request. The set language is then repeated back to the user for confirmation.
        attr = handler_input.attributes_manager.session_attributes
        attr["language"] = languageOption
        attr["state"] = "Language Set"
        speech_text = ('Thank you for selecting your language. '
                        'Your language is now set to {} ').format(languageOption)
        reprompt_text = 'To find out what you have set the language to, please ask me "What is the target language?"'
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
        if attr["state"] is None:
            outputSpeech = "No language has currently been set. Please set the language to continue";
        else:
            outputSpeech = "The language is currently set to {}".format(attr["language"]);
            
        return handler_input.response_builder.speak(speech_text).response;
  
""" Handler used to translate the phrase spoken by the user. The handler takes in the 
    captured phrase and utilises the utility functions below to either: check if the 
    phrase has previously been translated and exists in the DynamoDB, or translates the text
    by calling the API, then uses AWS Polly's text-to-speech functionality to create the audio 
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
                attr.get("state" == "Language Set"))
    
    def handle(self, handler_input):
        # type: (HandlerInput) -> Response

        
        # Firstly, the incoming session attributes are received and the sentence
        # that is 
        logger.info("In FunTranslateIntentHandler")(handler_input);
        attr = handler_input.attributes_manager.session_attributes;
        selected_language = attr.get("language");
        sentence = get_slot_value("sentence");
        key = sentence+selected_language;
        md5 = hashlib.md5(key);
        attr["last file key"] = key+' '+md5;
        
        try:
            tableEntry = table.get_item(
                    Key={
                        'phrase and language key': key,
                        'md5': md5
                    }
                );
                
            output = handler_input.response_builder.speak('The translation of the phrase {} in {} is: '.format(sentence, selected_language) + tableEntry['url'] +
                                                            ' You can ask me to repeat the sentence by saying repeat, or ask me to translate something else. Remember, you can only translate 5 sentences in the space of an hour' );
        except ClientError as e:
            logger.info("Could not access DynamoDB entry properly")(handler_input)
        else:
            translation = this.translateToTarget(sentence, selected_language)
            
            if attr["translation_state"] == "Unauthorized":
                output = handler_input.response_builder.speak("I'm sorry, the sentence could not be translated. Please try saying something else")
            elif attr["translation_state"] == "Limit Exceeded":
                output = handler_input.response_builder.speak("I'm sorry, you can only translate 5 sentences or phrases in the space of an hour.".set_should_end_session(True))
            else:
                # Put key and translation into dynamoDB table to facilitate case where user asks for translation of already existing sentence
                response = this.synthesizeSpeech(translation, voices[selected_language], handler_input);
                if (response != {} and "Audio Stream" in response):
                    logger.info("Uploading Audio File to S3")(handler_input);
                    
                    file_upload_bool = this.putFileIntoS3Bucket(key, md5);
                    
                    
                    if file_upload_bool == True:
                        
                        url = '<audio src= "https://s3.amazonaws.com/{}/{}/{}/translated.mp3/> '.format(bucketName, md5, key);
                        output = handler_input.response_builder.speak('The translation of the phrase {} in {} is: '.format(sentence, selected_language) + url +
                                                                       ' You can ask me to repeat the sentence by saying repeat, or ask me to translate something else. Remember, you can only translate 5 sentences in the space of an hour' );
                        this.uploadDetailsToDynamoDB(key, translation, md5, url);
                        
                    else:
                        
                        output = handler_input.response_builder.speak("I'm sorry, there was an error during translation");
                else:
                    output = handler_input.response_builder.speak("I'm sorry, there was an error during translation. Please try saying something else");
            
        return output.response;

""" Handler used to catch case where user attempts to translate a phrase before 
    the language has been set by the user. The handler simply checked whether the 
    state attribute has been changed to "Language Set" and off the basis of this, 
    the handler provides a reply telling the user to set a language instead.
"""       
class NoTargetLanguageIntentHandler(AbstractRequestHandler):        
        
    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        attr = handler_input.attributes_manager.session_attributes
        return (is_intent_name("TranslateIntent")(handler_input) and
                attr.get("state" != "Language Set"))
    
    def handle(self, handler_input):
        # type: (HandlerInput) -> Response

        logger.info("In NoTargetLanguageIntentHandler")(handler_input);
        speech = ('Please select a target translation language before attempting '
                  'to translate a phrase'
                  'You can select from Pig Latin, Dothraki and Shakespeare. Thank you.');
        return handler_input.response_builder.speak(speech_text).response;

""" Handler used to repeat the translated phrase back to the user, when they wish to hear
    it again. The handler uses the last file key session attribute logged when the phrase 
    is initially translated 
"""    
class RepeatIntentHandler(AbstractRequestHandler):
    
    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        return is_intent_name("RepeatPhraseIntent")(handler_input);
    
    def handle(self, handler_input):
        # type: (HandlerInput) -> Response
        
        logger.info("In FunTranslateIntentHandler")(handler_input);
        attr = handler_input.attributes_manager.session_attributes;
        
        if attr["last file key"] is None:
            
            outputSpeech = ('Sorry, it seems as though you have not said anything before for me to repeat'
                            'Please firstly say a phrase for me to translate.');
        # selected_language = attr.get("language");
        # sentence = get_slot_value("sentence");
        # key = selected_language+sentence;
        else:
            
            keyDict = attr["last file key"].split(1);
            try:
                tableEntry = table.get_item(
                    Key={
                        'phrase and language key': keyDict[0],
                        'md5': keyDict[1]
                    }
                );
                
                outputSpeech = ('The phrase {} in {} is: '.format(sentence, selected_language) + tableEntry['url'])
            except ClientError as e:
                logger.info("Could not access DynamoDB entry properly")(handler_input);
                outputSpeech = "I'm sorry, there was an error. Please try saying something else"
            
        
        return handler_input.response_builder.speak(outputSpeech).response;
        
# Utility functions

""" Function used to make API call to translate the input phrase from English into
    set target language. Based on the language that has been set as the language option,
    the function will call the relevant API path and translate the phrase into the 
    target language. 
"""
def translateToTarget(input_phrase, language):
    
    translation = "";
    attr = handler_input.attributes_manager.session_attributes;
    url = ('https://api.funtranslations.com/translate/'+
                language + 
                '.json?text=' + 
                input_phrase
                );
                
    try:
        translation_response = requests.get(url)
        if translation_response.status_code == 429:
            # NEED TO EXIT IF THIS IS TRUE IN HANDLER!!!
            attr["translation_state"] = "Limit Exceeded"
        elif translation_response.status_code == 401:
            attr["translation_state"] = "Unauthorized"
        else:
            txt = translation_response.text;
            x = txt.find("translated");
            y = txt.find("text");
            txt = txt[x:y];
            x = txt.find(":");
            y = txt.rfind(",");
            txt = txt[x+3:y-1];
            translation = txt;
            attr["translation_state"] = "Translated";
            
    except Exception as e:
        logger.error(e);
        return response;
    
    return translation;

""" Function used to convert the translated text into an audio file using functionality
    in AWS Polly. The out-of-the-box Polly function "synthesize_speech" is used to convert
    the SSML text into the required audio file with the  Polly voice defined for the language
    within the voices dictionary above
"""
def synthesizeSpeech(translated_text, voice):
    
    response = {};
    SSML = ('<speak><amazon:effect name="drc">'+
            translated_text + '</amazon:effect><prosody rate= "slow">' +
            '<amazon:effect name="drc"><p>' + translated_text +
            '</p></amazon:effect></prosody></speak>'
            );
    
    try:
        response = polly.synthesize_speech(OutputFormat = 'mp3',
                                Engine = 'standard',
                                Text = SSML,
                                TextType = 'ssml',
                                VoiceId = voice
                                );
    except Exception as e:
        logger.error(e);
        
    return response;

""" Function used to upload the audio file into the S3 bucket for storage. It takes 
    in the String key which will be the combination of sentence to be translated and the 
    target language, as well as the md5 hashed value of the key to place the audio file 
    into the S3 bucket for easy access.
"""
def putFileIntoS3Bucket(key, hash_val):
    # type: (String, String) -> bool
    keyVal = "{}/{}/translated.mp3".format(hash_val, key)
    try:
        s3.put_object(ACL='public-read', Bucket=bucketName, Key=keyVal);
        return True;
    except Exception as e:
        logger.error(e);
        return False;

""" Function used to upload the specified item into the DynamoDB table so that it
    can be accessed again if it has been previously translated. 
"""
def uploadDetailsToDynamoDB(key, translation, hash_val, url):
    
    try:
        table.put_item(
            Item={
                'phrase and language key': key,
                'hash': hash_val,
                'value': {
                    'translation': translation,
                    'url': url
                }
            }
            
        )
    except Exception as e:
        logger.error(e);

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
