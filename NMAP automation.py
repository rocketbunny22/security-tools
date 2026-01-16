import os


def nmap_scan(target_ip, options):
    command = "nmap " + options + " " + target_ip
    process = os.popen(command)
    results = str(process.read())
    return results


ip_address = "8.8.8.8"
options = "-sS -sV -p" 
print(nmap_scan(ip_address, options))
