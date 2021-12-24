#!/usr/bin/env bash

clear_line() {
    printf "\r\033[2K"
}

print_status() {
    printf "\e[3;4m%s\e[0m\r" "$1"
}

print_status_report() {
    clear_line
    print_status "$1"
}

print_status_success() {
    printf "\e[30;42m %s \e[0m" "$1"
    shift
    if [ ! -z $1 ]; then
        printf " \e[4m%s\e[0m" "$*"
    fi
    printf "\n"
}

print_status_error() {
    printf "\e[1;101m %s \e[0m\n" "$1"
}

if [[ $# < 1 ]]; then
    echo "brki.sh"
    echo "   Brkiziraj fajlove (da budu lijepi i hrskavi ko njegov tost)"
    echo ""
    echo "Usage: brki.sh file [file2 file3 ...]"
    echo "       eg. brki.sh a.mp4 b.webm"
    exit
fi

FILES=("$@")

MAX_FILE_LEN=-1
for str in "${FILES[@]}"; do
    filename="$(basename -- "$str")"
    extension="${filename##*.}"
    filename="${filename%.*}"

    if [[ ${#filename} -gt ${MAX_FILE_LEN} ]]; then
        MAX_FILE_LEN=${#filename}
    fi
done

total="${#FILES[@]}"

success=0

for filepath in "${FILES[@]}"; do
    location="$PWD"

    filename="$(basename -- "$filepath")"
    extension="${filename##*.}"
    filename="${filename%.*}"

    oldName="${filename}.${extension}"
    newName="${filename}.brki.mp4"

    oldFull="${location}/${oldName}"
    newFull="${location}/${newName}"

    if [ -f "$newFull" ]; then
        if [ -f "$oldFull" ]; then
            if command -v kioclient5 &>/dev/null; then
                kioclient5 move "$newFull" trash:/ 2>/dev/null
            elif command -v trash-put &>/dev/null; then
                trash-put "$newFull"
            fi
        fi
    fi

    printf "Brkiziranje \e[1;36;40m %-${MAX_FILE_LEN}s \e[0m... " "$filename"

    __OLD_TIMEFORMAT=$TIMEFORMAT
    export TIMEFORMAT='%3lR'
    res="`(time ffmpeg -y -loglevel panic -i "$oldFull" -max_muxing_queue_size 1024 -vf 'scale=144:-2' -af 'bass=g=-10,treble=g=5,volume=10dB,equalizer=f=2300:width_type=h:width=150:g=25,equalizer=f=2450:width_type=h:width=90:g=-18' -c:v libx264 -b:v 17k -maxrate 10k -ab 27k -map_metadata 0 "$newFull") 2>&1`"
    res_exit_code=$?
    cmd_duration="$(echo "$res" | tail -n1)"
    export TIMEFORMAT=${__OLD_TIMEFORMAT}
    unset __OLD_TIMEFORMAT

    if [[ "$res_exit_code" -ne '0' ]]; then
        print_status_error "DEAD ($res_exit_code)"
        rm "$newFull" 2>/dev/null
        continue
    fi

    if [ -z "`find "$newFull" -maxdepth 1 -type f -size +1k 2>/dev/null`" ]; then
        print_status_error "FAIL"
        rm "$newFull" 2>/dev/null
        continue
    fi

    touch -r "$oldFull" "$newFull"
    print_status_success "DONE" "$cmd_duration"
    ((success++))
done

print_status_success "FINISHED $success/$total"
echo ""
