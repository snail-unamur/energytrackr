#!/usr/bin/env bash
#------------------------------------------------------------------------------#
# energy-measurement.sh                                                        #
#------------------------------------------------------------------------------#
# Description:                                                                 #
#   Prepare the system for *repeatable, stable* energy measurements (Intel     #
#   RAPL) by disabling power-saving features and pinning frequencies.          #
#                                                                              #
#   **Everything is runtime-configurable** from a shell-style config file.     #
#   Example (copy to ~/.config/energy-measurement.conf and tweak):             #
#                                                                              #
#       ## ---- high-level switches (yes|no) ----                              #
#       USE_RFKILL=yes              # block/unblock all radios                 #
#       MANAGE_SERVICES=yes         # mask NetworkManager etc.                 #
#       MANAGE_MODULES=yes          # rmmod iwlwifi, btusb …                   #
#       TUNE_CPU=yes                # governor=userspace, fixed freq           #
#       TUNE_UNCORE=yes             # set uncore freq                          #
#       TUNE_GPU=yes                # set Intel GT min/max                     #
#       TUNE_AUDIO=yes              # snd_hda_intel power save                 #
#       TUNE_SATA=yes               # lpm-policy                               #
#                                                                              #
#       ## ---- detailed parameters ----                                       #
#       SERVICES_TO_DISABLE=(NetworkManager.service wpa_supplicant.service)    #
#       WIFI_BT_MODULES=(iwlmvm iwlwifi btusb bluetooth)                       #
#       CPU_FREQ_KHZ=2000000        # 2 GHz                                    #
#       UNC_FREQ_KHZ=2000000
#       GPU_CARD=card1              # /sys/class/drm/<card>/                   #
#       GPU_MIN_FREQ_MHZ=300
#       GPU_MAX_FREQ_MHZ=1100
#       SND_POW_SAVE=0              # 0 = disable                              #
#       SND_POW_CTRL=0              # 0 = disable                              #
#       SATA_POLICY=max_performance                                            #
#                                                                              #
# Usage (run as root):                                                         #
#   sudo ./energy-measurement.sh first-setup    # one-off, creates boot entry  #
#   sudo ./energy-measurement.sh setup          # enter measurement mode       #
#   sudo ./energy-measurement.sh revert-setup   # leave measurement mode       #
#   sudo ./energy-measurement.sh revert-first-setup  # drop custom boot entry  #
#------------------------------------------------------------------------------#

set -euo pipefail
trap 'echo -e "\e[31m✖ Error at line ${LINENO}\e[0m" >&2' ERR

# ----- coloured logging -------------------------------------------------------
CYAN=$'\e[96m'
GREEN=$'\e[32m'
RED=$'\e[31m'
RESET=$'\e[0m'
log() { echo -e "${CYAN}[INFO]${RESET}  $*"; }
warn() { echo -e "${RED}[WARN]${RESET}  $*" >&2; }

# ---------- default *flags* (over-ridable) ------------------------------------
USE_RFKILL=yes      # block/unblock radios
MANAGE_SERVICES=yes # mask / unmask systemd services
MANAGE_MODULES=yes  # remove / load wifi-bt modules
TUNE_CPU=yes        # governor/frequency pinning
TUNE_UNCORE=yes
TUNE_GPU=yes
TUNE_AUDIO=yes
TUNE_SATA=yes

# ---------- default *parameters* ---------------------------------------------
declare -a SERVICES_TO_DISABLE=(NetworkManager.service systemd-journald.service
    wpa_supplicant.service)
declare -a WIFI_BT_MODULES=(iwlmvm iwlwifi btusb bluetooth mac80211 cfg80211)
CPU_FREQ_KHZ=2000000
UNC_FREQ_KHZ=2000000
GPU_CARD=card1
GPU_MIN_FREQ_MHZ=300
GPU_MAX_FREQ_MHZ=1100
SND_POW_SAVE=0
SND_POW_CTRL=0
SATA_POLICY=max_performance

# ---------- helper: normalise booleans ----------------------------------------
bool() {
    # returns 0 (=true) if $1 represents yes/true/on/1, else 1
    [[ "${1,,}" =~ ^(yes|y|true|t|1|on)$ ]]
}

# ---------- load user/system config ------------------------------------------
load_configs() {
    log "Loading configs"
    local user_home
    if [[ $EUID -eq 0 && -n ${SUDO_USER:-} && $SUDO_USER != "root" ]]; then
        user_home=$(getent passwd "$SUDO_USER" | cut -d: -f6)
    else
        user_home="$HOME"
    fi
    log "User home: $user_home"
    for cfg in "/etc/energy-measurement.conf" "$user_home/.config/energy-measurement.conf"; do
        log "Checking: $cfg"
        if [[ -e $cfg ]]; then
            if [[ -r $cfg ]]; then
                log "Loading config $cfg"
                source "$cfg"
            else
                warn "Config $cfg exists but is not readable (permissions: $(stat -c '%A' "$cfg"))"
            fi
        fi
    done
}

# ---------- misc helpers ------------------------------------------------------
is_root() { [[ $(id -u) -eq 0 ]]; }

# ---------- bootloader detection ----------------------------------------------
detect_bootloader() {
    if bootctl is-installed &>/dev/null; then
        BOOTLOADER=systemd-boot
    elif [[ -f /etc/default/grub ]]; then
        BOOTLOADER=grub
    else
        warn "Unsupported bootloader: neither systemd-boot nor GRUB detected"
        exit 1
    fi
    log "Detected bootloader: $BOOTLOADER"
}

# ---------- GRUB helpers ------------------------------------------------------
grub_update() {
    if command -v update-grub &>/dev/null; then
        update-grub
    elif command -v grub-mkconfig &>/dev/null; then
        grub-mkconfig -o /boot/grub/grub.cfg
    elif command -v grub2-mkconfig &>/dev/null; then
        grub2-mkconfig -o /boot/grub2/grub.cfg
    else
        warn "No GRUB regeneration tool found (update-grub / grub-mkconfig / grub2-mkconfig)"
        exit 1
    fi
}

grub_first_setup() {
    local grub_file=/etc/default/grub
    local backup=/etc/default/grub.energy-backup
    [[ -f $backup ]] && {
        warn "Backup $backup already exists. Did you already run first-setup?"
        exit 1
    }
    cp "$grub_file" "$backup"
    log "Backed up $grub_file → $backup"
    sed -i 's/\(GRUB_CMDLINE_LINUX_DEFAULT="[^"]*\)"/\1 intel_pstate=disable cpuidle.off=1 idle=poll"/' "$grub_file"
    log "Added kernel parameters to $grub_file"
    grub_update
    log "GRUB configuration updated"
}

grub_revert_first_setup() {
    local grub_file=/etc/default/grub
    local backup=/etc/default/grub.energy-backup
    [[ -f $backup ]] || {
        warn "Backup $backup not found. Was first-setup run?"
        exit 1
    }
    cp "$backup" "$grub_file"
    log "Restored $grub_file from $backup"
    grub_update
    rm -f "$backup"
    log "Removed backup $backup"
}

# ---------- systemd-boot helpers ----------------------------------------------
systemd_boot_first_setup() {
    local custom
    custom=$(prepare_custom_entry)
    for p in intel_pstate=disable cpuidle.off=1 idle=poll; do
        modify_param add "$p" "$custom"
    done
    bootctl update
    log "Created boot entry: $(basename "$custom")"
}

systemd_boot_revert_first_setup() {
    local orig custom
    orig=$(get_boot_entry)
    custom="/boot/loader/entries/$(basename "$orig" .conf)-energy.conf"
    [[ -f $custom ]] && {
        rm -f "$custom"
        bootctl update
        log "Removed $(basename "$custom")"
    }
}

ensure_user_config() {
    local user_home
    if [[ $EUID -eq 0 && -n ${SUDO_USER:-} && $SUDO_USER != "root" ]]; then
        user_home=$(getent passwd "$SUDO_USER" | cut -d: -f6)
    else
        user_home="$HOME"
    fi
    local user_cfg="$user_home/.config/energy-measurement.conf"
    [[ -f $user_cfg ]] && {
        log "User config exists: $user_cfg"
        return
    }
    local default_cfg
    default_cfg="$(dirname "$0")/energy-measurement.conf"
    if [[ -f $default_cfg ]]; then
        mkdir -p "$user_home/.config"
        cp "$default_cfg" "$user_cfg"
        log "Copied default config to $user_cfg"
    else
        warn "Default template not found ($default_cfg)."
    fi
}

get_boot_entry() {
    local entry
    entry=$(find /boot/loader/entries -name '*.conf' ! -name '*-energy.conf' -print -quit)
    [[ $entry ]] || {
        warn "systemd-boot entry not found"
        exit 1
    }
    echo "$entry"
}

prepare_custom_entry() {
    local orig base custom
    orig=$(get_boot_entry)
    base=$(basename "$orig" .conf)
    custom="/boot/loader/entries/${base}-energy.conf"
    [[ -e $custom ]] || {
        cp "$orig" "$custom"
        log "Created $custom"
    }
    echo "$custom"
}

modify_param() { # add|remove param file
    local mode=$1 param=$2 file=$3
    if [[ $mode == add ]]; then
        grep -qw -- "$param" "$file" || sed -i "/^options/s/$/ $param/" "$file"
    else
        sed -i "s/ *$param//" "$file"
    fi
}

manage_services() {
    bool "$MANAGE_SERVICES" || {
        log "Service management disabled"
        return
    }
    local action=$1
    for svc in "${SERVICES_TO_DISABLE[@]}"; do
        systemctl "$action" $([[ $action == mask ]] && echo --now || echo --now) "$svc" &>/dev/null ||
            warn "systemctl $action $svc failed"
        log "${action^} $svc"
    done
}

manage_modules() {
    bool "$MANAGE_MODULES" || {
        log "Module management disabled"
        return
    }
    local action=$1
    for mod in "${WIFI_BT_MODULES[@]}"; do
        if [[ $action == disable ]]; then
            modprobe -r "$mod" &>/dev/null || true
        else
            modprobe "$mod" &>/dev/null || true
        fi
    done
}

manage_rfkill() {
    bool "$USE_RFKILL" || {
        log "rfkill disabled via config"
        return
    }
    rfkill "$@" all &>/dev/null || warn "rfkill not available"
}

apply_power_settings() {
    bool "$TUNE_CPU" && {
        local governor
        local available
        available=$(</sys/devices/system/cpu/cpu0/cpufreq/scaling_available_governors)

        if [[ $available =~ userspace ]]; then
            governor=userspace
        elif [[ $available =~ powersave ]]; then
            governor=powersave
            warn "Userspace governor not available, falling back to powersave"
        else
            warn "Neither userspace nor powersave governor available, skipping CPU tuning"
            governor=""
        fi

        if [[ -n $governor ]]; then
            log "CPU governor $governor, freq ${CPU_FREQ_KHZ} kHz"
            echo "$governor" | tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor
            for f in scaling_{min,max}; do
                echo "$CPU_FREQ_KHZ" | tee /sys/devices/system/cpu/cpu*/cpufreq/${f}_freq
            done
        fi
    }

    bool "$TUNE_UNCORE" && {
        log "Uncore → ${UNC_FREQ_KHZ} kHz; turbo boost off"
        echo 0 | tee /sys/devices/system/cpu/cpufreq/boost || true
        for f in /sys/devices/system/cpu/intel_uncore_frequency/*/min_freq_khz /sys/devices/system/cpu/intel_uncore_frequency/*/max_freq_khz; do
            [[ -w $f ]] && echo "$UNC_FREQ_KHZ" >"$f"
        done
    }

    bool "$TUNE_GPU" && {
        log "GPU $GPU_CARD freq ${GPU_MIN_FREQ_MHZ}-${GPU_MAX_FREQ_MHZ} MHz"
        echo "$GPU_MIN_FREQ_MHZ" >/sys/class/drm/${GPU_CARD}/gt_min_freq_mhz 2>/dev/null || true
        echo "$GPU_MAX_FREQ_MHZ" >/sys/class/drm/${GPU_CARD}/gt_max_freq_mhz 2>/dev/null || true
    }

    bool "$TUNE_AUDIO" && {
        log "Audio power save disabled"
        [[ -w /sys/module/snd_hda_intel/parameters/power_save ]] &&
            echo "$SND_POW_SAVE" >/sys/module/snd_hda_intel/parameters/power_save
        [[ -w /sys/module/snd_hda_intel/parameters/power_save_controller ]] &&
            echo "$SND_POW_CTRL" >/sys/module/snd_hda_intel/parameters/power_save_controller
    }

    bool "$TUNE_SATA" && {
        log "SATA link power → $SATA_POLICY"
        for host in /sys/class/scsi_host/host*; do
            [[ -w $host/link_power_management_policy ]] &&
                echo "$SATA_POLICY" >"$host/link_power_management_policy"
        done
    }
}

revert_power_settings() {
    bool "$TUNE_CPU" && {
        log "Re-enable CPU boost"
        echo 1 | tee /sys/devices/system/cpu/cpufreq/boost || true
    }
    bool "$TUNE_AUDIO" && {
        log "Restore audio power save defaults"
        echo 1 >/sys/module/snd_hda_intel/parameters/power_save 2>/dev/null || true
        echo 1 >/sys/module/snd_hda_intel/parameters/power_save_controller 2>/dev/null || true
    }
    bool "$TUNE_GPU" && {
        log "Reset GPU freq"
        echo 300 >/sys/class/drm/${GPU_CARD}/gt_min_freq_mhz 2>/dev/null || true
        echo 1100 >/sys/class/drm/${GPU_CARD}/gt_max_freq_mhz 2>/dev/null || true
    }
    bool "$TUNE_SATA" && {
        log "SATA link power → med_power_with_dipm"
        for host in /sys/class/scsi_host/host*; do
            [[ -w $host/link_power_management_policy ]] &&
                echo med_power_with_dipm >"$host/link_power_management_policy"
        done
    }
}

main() {
    is_root || {
        warn "Run as root"
        exit 1
    }
    load_configs
    detect_bootloader
    case "${1:-}" in
    first-setup)
        ensure_user_config
        case "$BOOTLOADER" in
            systemd-boot) systemd_boot_first_setup ;;
            grub)         grub_first_setup ;;
        esac
        ;;
    setup)
        log "Verifying kernel parameters…"
        for p in intel_pstate=disable cpuidle.off=1 idle=poll; do
            grep -qw "$p" /proc/cmdline || {
                warn "Kernel parameter $p missing. Did you reboot after first-setup?"
                exit 1
            }
        done
        echo -1 >/proc/sys/kernel/perf_event_paranoid
        manage_services mask
        manage_rfkill block
        manage_modules disable
        apply_power_settings
        log "Measurement mode enabled"
        ;;
    revert-setup)
        log "Reverting settings"
        revert_power_settings
        manage_modules enable
        manage_rfkill unblock
        manage_services unmask
        log "Measurement mode disabled"
        ;;
    revert-first-setup)
        case "$BOOTLOADER" in
            systemd-boot) systemd_boot_revert_first_setup ;;
            grub)         grub_revert_first_setup ;;
        esac
        ;;
    *)
        echo "Usage: $0 {first-setup|setup|revert-setup|revert-first-setup}" >&2
        exit 1
        ;;
    esac
}

clear
main "$@"
