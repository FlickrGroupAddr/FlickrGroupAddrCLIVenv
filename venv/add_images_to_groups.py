import json
import argparse
import pprint
import flickrapi
import flickrapi.auth
import os.path
import datetime
import glob


def _create_flickr_api_handle( app_flickr_api_key_info, user_flickr_auth_info ):
    # Create an OAuth User Token that flickr API library understands
    api_access_level = "write"
    flickrapi_user_token = flickrapi.auth.FlickrAccessToken(
        user_flickr_auth_info['user_oauth_token'],
        user_flickr_auth_info['user_oauth_token_secret'],
        api_access_level,
        user_flickr_auth_info['user_fullname'],
        user_flickr_auth_info['username'],
        user_flickr_auth_info['user_nsid'])

    flickrapi_handle = flickrapi.FlickrAPI(app_flickr_api_key_info['api_key'],
                                           app_flickr_api_key_info['api_key_secret'],
                                           token=flickrapi_user_token,
                                           store_token=False,
                                           format='parsed-json')

    return flickrapi_handle


def _persist_request_set_state( request_set_state, request_set_state_json_filename  ):
    with open( request_set_state_json_filename, "w" ) as request_set_state_handle:
        json.dump( request_set_state, request_set_state_handle, indent=4, sort_keys=True )


def _create_state_entry( request_set_state, photo_id, group_id ):
    state_key = _generate_state_key(photo_id, group_id)
    request_set_state[state_key] = {
        'photo_added': False,
        'fga_add_attempts': [],
    }

def _read_request_set_with_state( request_set_json_filename, request_set_state_json_filename ):

    with open( request_set_json_filename, "r") as request_set_handle:
        request_set_info = json.load( request_set_handle )['fga_request_set']

    if os.path.isfile( request_set_state_json_filename  ):
        with open(request_set_state_json_filename , "r") as request_set_state_handle:
            request_set_state_info = json.load(request_set_state_handle)
    else:
        # First time through, initialize state dictionary
        request_set_state_info = {}

    return {
        'request_set'           : request_set_info,
        'request_set_state'     : request_set_state_info,
    }


def _read_user_flickr_auth_info(args):
    with open( args.user_auth_info_json, "r") as user_auth_info_handle:
        user_auth_info = json.load( user_auth_info_handle )

    return user_auth_info


def _read_app_flickr_api_key_info(args):
    with open(args.app_api_key_info_json, "r") as app_api_key_info_handle:
        app_api_key_info = json.load(app_api_key_info_handle)

    return app_api_key_info


def _parse_args():
    arg_parser = argparse.ArgumentParser(description="Get list of groups for this user")
    arg_parser.add_argument( "app_api_key_info_json", help="JSON file with app API auth info")
    arg_parser.add_argument( "user_auth_info_json", help="JSON file with user auth info")
    arg_parser.add_argument( "request_set_json_dir", help="Directory of JSON files with picture->group add requests")
    return arg_parser.parse_args()


def _generate_state_key( photo_id, group_id ):
    return f"photo_{photo_id}_group_{group_id}"


def _add_pic_to_group(flickrapi_handle, photo_id, group_id, state_entry ):
    # Get current timestamp
    current_timestamp = datetime.datetime.now( datetime.timezone.utc ).replace( microsecond=0 )
    #print( f"Timestamp of this attempt: {current_timestamp.isoformat()}" )

    try:
        print(f"\t* Attempting to add photo {photo_id} to group {group_id}")
        flickrapi_handle.groups.pools.add( photo_id=photo_id, group_id=group_id )

        # Success!
        print( "\t\tSuccess!")
        state_entry['photo_added'] = True
        state_entry_add_attempt_details = {
            'timestamp' : current_timestamp.isoformat(),
            'status'    : 'success_added',
        }

    except flickrapi.exceptions.FlickrError as e:
        error_string = str(e)
        adding_to_pending_queue_error_msg = "Error: 6:"
        if error_string.startswith(adding_to_pending_queue_error_msg):
            state_entry_add_attempt_details = {
                'timestamp': current_timestamp.isoformat(),
                'status': 'success_queued',
            }
            print( "\t\tSuccess (added to pending queue)!")
        else:
            print( f"\t\t{str(e)}" )
            state_entry_add_attempt_details = {
                'timestamp'     : current_timestamp.isoformat(),
                'status'        : 'fail',
                'error_message' : str(e),
            }

    state_entry['fga_add_attempts'].append( state_entry_add_attempt_details )


def _has_add_attempt_within_same_utc_day(state_entry):
    has_add_attempt_within_same_utc_day = False
    #seconds_in_one_day = 86400
    current_timestamp = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
    for curr_add_attempt in state_entry['fga_add_attempts']:
        add_attempt_timestamp = datetime.datetime.fromisoformat(curr_add_attempt['timestamp'])
        if current_timestamp.date() == add_attempt_timestamp.date():
            has_add_attempt_within_same_utc_day = True
            break

    #print(f"\t\tDate {add_attempt_timestamp.date()} == {current_timestamp.date()}? {has_add_attempt_within_same_utc_day}")

    return has_add_attempt_within_same_utc_day


def _is_request_set_json( json_filename ):
    with open( json_filename, "r" ) as json_handle:
        parsed_json = json.load( json_handle )

    return 'fga_request_set' in parsed_json


def _get_group_memberships_for_pic( flickrapi_handle, pic_id ):
    pic_contexts = flickrapi_handle.photos.getAllContexts( photo_id=pic_id )

    #print( "Contexts:\n" + json.dumps(pic_contexts, indent=4, sort_keys=True))
    group_memberships = {}
    if 'pool' in pic_contexts:
        for curr_group in pic_contexts['pool']:
            group_memberships[ curr_group['id']] = curr_group

    #print( "Group memberships:\n" + json.dumps(group_memberships, indent=4, sort_keys=True))

    return group_memberships


def _add_pics_to_groups( args,  app_flickr_api_key_info, user_flickr_auth_info ):
    flickrapi_handle = _create_flickr_api_handle(app_flickr_api_key_info, user_flickr_auth_info)

    stats = {
        'skipped_already_added'     : 0,
        'skipped_too_soon'          : 0,
        'attempted_success_added'  : 0,
        'attempted_success_queued'  : 0,
        'attempted_fail'            : 0,
    }

    today_date_utc = datetime.datetime.now( datetime.timezone.utc ).date()

    # Iterate over all JSON files in the specified directory
    for curr_json_file in glob.glob( os.path.join( args.request_set_json_dir, "*.json") ):
        if _is_request_set_json(curr_json_file):
            print(f"\nReading {curr_json_file}")
            request_set_state_json_filename = curr_json_file.replace(".json", ".state.json")
            #print( f"{curr_json_file} is a request set JSON")
            request_set_info = _read_request_set_with_state( curr_json_file, request_set_state_json_filename )
            #print( f"Got request set:\n{json.dumps(request_set_info, indent=4, sort_keys=True)}")

            request_state_info = request_set_info['request_set_state']

            for current_pic_id in request_set_info['request_set']:
                current_pic_info = request_set_info['request_set'][current_pic_id]
                #print( f"Current entry:\n{json.dumps(request_set_info['request_set'][current_pic_id], indent=4, sort_keys=True)}")

                pic_group_memberships = _get_group_memberships_for_pic( flickrapi_handle, current_pic_id )

                # Get target state list of groups (full list we want to add to eventually)
                desired_list_of_groups = {}
                for current_group_entry in current_pic_info:
                    # Take first token (separated by whitespace) as the group NSID. The rest is human readability fluff
                    current_group_id = current_group_entry.split()[0]
                    desired_list_of_groups[current_group_id] = None

                # Subtract current memberships from desired to obtain list that we should *consider* trying
                groups_that_pic_is_not_in = []
                for curr_desired in sorted(desired_list_of_groups):
                    #print( f"\tEvaluating group {curr_desired} for pic {current_pic_id}")
                    if curr_desired not in pic_group_memberships:
                        groups_that_pic_is_not_in.append( curr_desired )
                        #print( f"\t{current_pic_id} is not in {curr_desired}, one we should consider")
                    else:
                        #print( f"\t\tPic is already in {curr_desired}, skipping" )
                        stats['skipped_already_added'] += 1

                # Iterate over all the groups we're thinking to add this pic to
                for current_group_id in groups_that_pic_is_not_in:
                    # Check state on this entry to make sure it isn't too early to try
                    state_key = _generate_state_key( current_pic_id, current_group_id )
                    #print( f"State key: {state_key}")
                    if state_key in request_state_info:
                        state_entry = request_state_info[state_key]
                        if _has_add_attempt_within_same_utc_day(state_entry):
                            print( f"\tPhoto {current_pic_id} -> group {current_group_id} already attempted today ({today_date_utc}, UTC), skipping" )
                            stats['skipped_too_soon'] += 1
                            continue
                    else:
                        #print( f"INFO: Creating state entry for pic {current_pic_id} into group {current_group_id} as it wasn't in state info")
                        _create_state_entry(request_state_info, current_pic_id, current_group_id )
                        state_entry = request_state_info[state_key]

                    # Attempt add, because either state says we haven't tried during current UTC day or there *was* no state yet
                    #print( "attempting add")
                    _add_pic_to_group( flickrapi_handle, current_pic_id, current_group_id, state_entry )
                    if state_entry['fga_add_attempts'][-1]['status'] == 'success_added':
                        stats['attempted_success_added'] += 1
                    elif state_entry['fga_add_attempts'][-1]['status'] == 'success_queued':
                        stats['attempted_success_queued'] += 1
                    else:
                        stats['attempted_fail'] += 1

            _persist_request_set_state( request_set_info['request_set_state'], request_set_state_json_filename )
        else:
            #print( f"\tSkipping {curr_json_file}, not a request set file")
            pass

    return stats

def _main():
    args = _parse_args()

    # Get auth info
    app_flickr_api_key_info = _read_app_flickr_api_key_info( args )
    user_flickr_auth_info = _read_user_flickr_auth_info( args )

    # Ready to kick off the operations
    stats = _add_pics_to_groups( args, app_flickr_api_key_info, user_flickr_auth_info )
    print( "\nOperation stats:\n" + json.dumps(stats, indent=4, sort_keys=True))


if __name__ == "__main__":
    _main()