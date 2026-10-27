pidfile_live() {
    local file="$1" pid saved_start current_start
    [[ -s "$file" ]] || return 1
    read -r pid saved_start <"$file"
    [[ "$pid" =~ ^[0-9]+$ && "$saved_start" =~ ^[0-9]+$ ]] || return 1
    kill -0 "$pid" 2>/dev/null || return 1
    current_start="$(awk '{print $22}' "/proc/$pid/stat" 2>/dev/null)"
    [[ "$current_start" == "$saved_start" ]]
}

pidfile_pid() {
    local pid ignored
    read -r pid ignored <"$1"
    printf '%s\n' "$pid"
}

write_pidfile() {
    local pid="$1" file="$2" start
    start="$(awk '{print $22}' "/proc/$pid/stat")"
    printf '%s %s\n' "$pid" "$start" >"$file"
}
