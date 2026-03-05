# Wireless Security Audit Context — Harrah's Cherokee Casino Resort

## Facility
- Harrah's Cherokee Casino Resort, Cherokee, NC
- Operated by Caesars Entertainment / Eastern Band of Cherokee Indians
- Full-service casino resort: gaming floor, hotel, spa, conference center, restaurants

## Known Infrastructure (from wardrive survey)
- ~400 unique BSSIDs across 18 SSIDs, estimated ~275 physical APs
- Primary vendor: Ruckus Wireless (OUI 28:B3:71, B4:79:C8, 84:23:88, 70:CA:97, 8C:7A:15, CC:1B:5A)
- Secondary vendor: Aruba/HPE (OUI 8C:7A:15, F0:6F:CE, 84:23:88)
- Legacy vendor: Colubris Networks (OUI 00:03:52) — acquired by HP in 2008, hardware is 15+ years old, end-of-life
- Standard 2.4GHz deployment on channels 1, 6, 11

## Critical Finding: Open Guest Networks
Six guest-facing SSIDs use OPEN authentication (zero encryption):

| SSID | APs | Purpose | Hardware |
|------|-----|---------|----------|
| Caesar_Resorts | 55 | Main guest WiFi (facility-wide) | Ruckus |
| Harrahs_CONFERENCE | 19 | Conference room WiFi | Ruckus |
| HarrahsRoomInternet | 4 | Hotel room internet | Colubris (EOL!) |
| Harrahs_GUEST | 2 | Guest network | Ruckus |
| Harrahs_LOBBY | 1 | Lobby WiFi | Ruckus |
| che_edr | 1 | Electronic Data Room or EDR system | Ruckus |

**Impact**: 82 APs transmitting all guest traffic in plaintext. Any device in range can passively capture login credentials, email, browsing activity, DNS queries over non-HTTPS connections. Evil Twin attacks trivial — broadcast fake "Caesar_Resorts", guests auto-connect.

## High Finding: Internal Network Architecture Disclosed
SSID naming reveals complete internal segmentation:

| SSID | APs | Auth | What It Reveals |
|------|-----|------|-----------------|
| SurvDept121 | 2 | WPA2-PSK | Surveillance dept AND physical room number (121) |
| che_extaudit | 5 | WPA2-PSK | External auditor / gaming commission network |
| HOTSOS | 4 | WPA/WPA2 | Amadeus HotSOS hotel operations platform (has legacy WPA1!) |
| TBLSIGN | 12 | WPA2-PSK | Gaming table digital signage |
| DELTA | 77 | WPA2 | Delta Technology casino management system |
| che_assoc | 64 | WPA2-PSK | Employee/associate WiFi |
| CHEVIPHOST | 60 | WPA2-PSK | VIP host services |
| che_hccr | 29 | WPA2-PSK | Harrah's Cherokee Casino Resort internal |
| HarrahsGaming | ? | WPA2-PSK | Gaming operations |
| Staycast-Device | 25 | WPA2-PSK | In-room Chromecast casting |
| che_event | 21 | WPA2-PSK | Event management |
| Che_Spa | 14 | WPA2-PSK | Spa operations |
| che_exec | 5 | WPA2-PSK | Executive management |

**Key concerns**:
- ALL internal networks use PSK (Pre-Shared Key) not Enterprise (802.1X) — one compromised password = full network access
- SurvDept121 exposes the casino's "eye in the sky" surveillance operation location
- che_extaudit: shared PSK with rotating external auditors = effectively a known credential
- HOTSOS still has legacy WPA1 (TKIP) support enabled — known cryptographic weaknesses

## High Finding: End-of-Life Hardware
4 APs serving HarrahsRoomInternet are Colubris Networks (OUI 00:03:52). Company acquired by HP in 2008. Hardware is ~15+ years old, no security patches, no vendor support. Serving hotel rooms with OPEN auth.

## Context: 2023 Caesars Breach
- September 2023: Scattered Spider breached Caesars Entertainment via social engineering
- Exfiltrated loyalty database (SSNs, driver's licenses)
- Caesars paid $15M ransom; MGM lost $110M in parallel attack
- Post-breach analysis cited insufficient network segmentation
- Current WiFi infrastructure presents LOWER barrier: no skill required, 55 open APs, network layout publicly broadcast, passive and undetectable

## Remediation Priorities
1. **IMMEDIATE**: Enable WPA3-OWE (Opportunistic Wireless Encryption) on all guest networks — provides encryption without passwords, supported by existing Ruckus hardware
2. **IMMEDIATE**: Investigate and encrypt che_edr
3. **SHORT-TERM**: Migrate all internal networks from PSK to WPA2/WPA3-Enterprise (802.1X with RADIUS)
4. **SHORT-TERM**: Rename internal SSIDs to not reveal function (e.g. "CHE-CORP-01" instead of "SurvDept121")
5. **SHORT-TERM**: Replace Colubris EOL hardware
6. **MEDIUM-TERM**: Deploy wireless intrusion prevention system (WIPS)
7. **MEDIUM-TERM**: Disable legacy WPA1/TKIP on HOTSOS
