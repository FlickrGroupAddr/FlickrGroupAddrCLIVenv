import argparse
import json
import flickrapi
import re
import html
import copy
import os.path


def _persist_request_set_to_disk( args, request_set ):
    for photo_id in request_set['fga_request_set']:
        with open( os.path.join(args.request_set_json_dir, f"fga_request_set_photo_{photo_id}.json"), "w") as request_set_handle:
            json.dump( request_set, request_set_handle, indent=4, sort_keys=True )


def _determine_subsets( group_memberships, currently_selected_groups ):
    subsets = {
        'selected'      : [],
        'unselected'    : [],
    }

    for curr_name_index in sorted(group_memberships):
        #print( f"Found group {human_readable_version}")

        if curr_name_index in currently_selected_groups:
            proper_subset = subsets['selected']
            #print( "\tGroup is selected")
        else:
            proper_subset = subsets['unselected']
            #print( "\tGroup is not selected")

        proper_subset.append( curr_name_index )

    return subsets


def _create_fga_request_set( flickapi_handle, group_memberships, picture_id ):
    currently_selected_groups = {}

    while True:
        print( f"\n\nPicture ID: {picture_id}")
        group_subsets = _determine_subsets( group_memberships, currently_selected_groups )

        print( "\nSelected Groups:\n" )

        for curr_group_index in group_subsets['selected']:
            print(f"\t{group_memberships[curr_group_index]['display']}" )

        print( "\n\nUnselected Groups:\n" )

        for curr_group_index in group_subsets['unselected']:
            print(f"\t{group_memberships[curr_group_index]['display']}" )

        selected_group_key_str = str( input("\n\nGroup ID (Enter to exit): ") )

        #print( f"Got input: \"{selected_group_key}\"")

        if not selected_group_key_str:
            break

        selected_group_key = int( selected_group_key_str )

        if selected_group_key < 1 or selected_group_key > len(group_memberships):
            print( f"WARNING: {selected_group_key} is an invalid entry, ignoring and trying again" )
            continue

        # If that group index is found in selected groups, delete it
        if selected_group_key in currently_selected_groups:
            del currently_selected_groups[selected_group_key]
        else:
            currently_selected_groups[selected_group_key] = None

    print( "Broke out of loop")

    # Build the request set
    request_set_entries = []
    for name_index in sorted(currently_selected_groups):
        request_set_entries.append( f"{group_memberships[name_index]['nsid']} - {group_memberships[name_index]['name']}")

    fga_request_set = {
        "fga_request_set": {
            picture_id: request_set_entries
        }
    }

    print( json.dumps( fga_request_set, indent=4, sort_keys=True ) )

    return fga_request_set


def _get_picture_id():
    # Get pic ID from URL
    picture_url = str( input( "\nEnter picture's URL on Flickr: "))

    # Find the picture ID which should be the only token with 8+ numeric digits
    search_results = re.findall( r'\/(\d{8,})\/', picture_url )
    if len( search_results) != 1:
        raise ValueError("Could not find picture ID in URL")

    #print(f"Search results: {search_results}")
    extracted_pic_id = search_results[0]
    print( f"Parsed picture ID {extracted_pic_id}")
    return extracted_pic_id


def _get_user_groups(flickrapi_handle):
    # Test our handle, print out our authenticated NSID or something
    user_groups = flickrapi_handle.groups.pools.getGroups()['groups']['group']

    #pprint.pprint( user_groups )
    group_membership_info = {}
    # Sort the list of user group names now and assign them a display key now
    group_name_list= []
    for curr_user_group in user_groups:
        curr_user_group['name'] = html.unescape(curr_user_group['name'])
        group_name_list.append( curr_user_group['name'] )

    # Now sort the list so we can have an index
    sorted_group_name_list = sorted( group_name_list, key=str.casefold )

    # Key the dictionary of group info by name index
    for (name_index, curr_sorted_name) in enumerate(sorted_group_name_list):
        for curr_user_group in user_groups:
            if curr_sorted_name == curr_user_group['name']:
                group_details = {
                    'name': curr_user_group['name'],
                    'display': f"{name_index + 1:3d}: {curr_sorted_name} ({curr_user_group['nsid']})",
                    'nsid': curr_user_group['nsid'],
                }
            group_membership_info[ name_index + 1 ] = group_details

    return group_membership_info


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
    arg_parser.add_argument( "request_set_json_dir", help="Directory where FGA request set JSON files should be stored" )
    return arg_parser.parse_args()


def _main():
    args = _parse_args()

    app_flickr_api_key_info = _read_app_flickr_api_key_info( args )
    user_flickr_auth_info = _read_user_flickr_auth_info( args )
    flickapi_handle = _create_flickr_api_handle(app_flickr_api_key_info, user_flickr_auth_info)
    group_memberships = _get_user_groups(flickapi_handle)
    #print( "Memberships:\n" + json.dumps(group_memberships, indent=4, sort_keys=True))

    picture_id = _get_picture_id()
    request_set = _create_fga_request_set( flickapi_handle, group_memberships, picture_id )
    _persist_request_set_to_disk( args, request_set )


if __name__ == "__main__":
    _main()