#!/usr/bin/env bash
SESSION_ID_FILE="$HOME/.config/.secrets/instagram"

function get-post-id() {
  POST_URL="$1"
  if [ -z "$POST_URL" ]; then
    read POST_URL
  fi

  url-info "$POST_URL" |
    jq -r '.[0].path' |
    sed -E 's|.*/(.*)/$|\1|'
}

function get-query() {
  POST_ID="$1"
  if [ -z "$POST_ID" ]; then
    read POST_ID
  fi

  QUERY_TEMPLATE="$(
    cat <<-'QUERY_TEMPLATE'
{
    "shortcode": "%s",
    "child_comment_count": 0,
    "fetch_comment_count": 0,
    "parent_comment_count": 0,
    "has_threaded_comments": true
}
QUERY_TEMPLATE
  )"

  printf "$QUERY_TEMPLATE" "$POST_ID" |
    jq -r "tostring"
}

function get-query-hash() {
  echo '2efa04f61586458cef44441f474eee7c'
}

function get-api-response() {
  POST_URL="$1"
  if [ -z "$POST_URL" ]; then
    read POST_URL
  fi

  POST_ID="$(get-post-id "$POST_URL")"
  QUERY="$(get-query "$POST_ID")"
  QUERY_HASH="$(get-query-hash "$QUERY" "$POST_ID")"

  if [ -f "$SESSION_ID_FILE" ]; then
    curl \
      --silent \
      --get \
      --data-urlencode "query_hash=$QUERY_HASH" \
      --data-urlencode "variables=$QUERY" \
      --header "cookie: sessionid=$(cat "$SESSION_ID_FILE")" \
      'https://www.instagram.com/graphql/query'
  else
    curl \
      --silent \
      --get \
      --data-urlencode "query_hash=$QUERY_HASH" \
      --data-urlencode "variables=$QUERY" \
      'https://www.instagram.com/graphql/query'
  fi
}

function get-post-media() {
  POST_URL="$1"
  if [ -z "$POST_URL" ]; then
    read POST_URL
  fi

  API_RESPONSE="$(
    echo "$POST_URL" |
      get-api-response
  )"

  MULTIPLE_MEDIA="$(
    echo "$API_RESPONSE" |
      jq -r '.data.shortcode_media.edge_sidecar_to_children // ""'
  )"

  if [ ! -z "$MULTIPLE_MEDIA" ]; then
    echo "$MULTIPLE_MEDIA" |
      jq -r '.edges | .[].node | (.video_url // .display_url)'
  else
    echo "$API_RESPONSE" |
      jq -r '.data.shortcode_media.display_url'
  fi
}

get-post-media "$1"
