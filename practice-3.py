#!/usr/bin/env python3
import argparse
import subprocess
import json
import requests
import tempfile
import os
import time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

def send_telegram_message(bot_token, chat_id, message):
    """Send message to Telegram bot"""
    if not bot_token or not chat_id:
        print("Telegram not configured - skipping message")
        return None
    
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        'chat_id': chat_id,
        'text': message,
        'parse_mode': 'HTML'
    }
    try:
        response = requests.post(url, data=payload, timeout=10)
        return response.json()
    except Exception as e:
        print(f"Telegram error: {e}")
        return None

def masscan_ips(ip_list, ports, rate=1000, timeout=2):
    """Use masscan to quickly scan for open ports"""
    results = []
    
    # Create temp file with IPs
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
        for ip in ip_list:
            f.write(f"{ip}\n")
        temp_file = f.name
    
    try:
        # Run masscan
        cmd = [
            'masscan',
            '-iL', temp_file,
            '-p', ports,
            '--rate', str(rate),
            '--wait', '0',
            '-oJ', '-'
        ]
        
        print(f"Running masscan: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        
        if result.returncode == 0:
            try:
                scan_data = json.loads(result.stdout)
                for item in scan_data:
                    if 'ip' in item and 'ports' in item:
                        results.append({
                            'ip': item['ip'],
                            'port': item['ports'][0]['port'],
                            'status': 'open'
                        })
            except json.JSONDecodeError:
                print("Masscan returned invalid JSON")
        else:
            print(f"Masscan failed: {result.stderr}")
            
    except subprocess.TimeoutExpired:
        print("Masscan timed out")
    except Exception as e:
        print(f"Masscan error: {e}")
    finally:
        os.unlink(temp_file)
    
    return results

def verify_service(ip, port, service, timeout=2):
    """Verify if service is actually running on the port"""
    try:
        if service.lower() == 'ssh':
            # Quick SSH banner check
            cmd = ['nc', '-z', '-w', str(timeout), ip, str(port)]
        elif service.lower() == 'rdp':
            # Quick RDP check
            cmd = ['nc', '-z', '-w', str(timeout), ip, str(port)]
        else:
            return False
        
        result = subprocess.run(cmd, capture_output=True, timeout=timeout+1)
        return result.returncode == 0
        
    except Exception as e:
        print(f"Error verifying {ip}:{port} - {e}")
        return False

def main():
    parser = argparse.ArgumentParser(description='IP Scanner and Service Verifier')
    parser.add_argument('--service', required=True, choices=['ssh', 'rdp'], help='Service to scan')
    parser.add_argument('--ip-list', required=True, help='Path to IP list file')
    parser.add_argument('--timeout', type=int, default=2, help='Timeout per IP in seconds')
    parser.add_argument('--bot-token', help='Telegram Bot Token')
    parser.add_argument('--chat-id', help='Telegram Chat ID')
    parser.add_argument('--max-workers', type=int, default=50, help='Max concurrent verifications')
    
    args = parser.parse_args()
    
    # Read IP list
    try:
        with open(args.ip_list, 'r') as f:
            ip_list = [line.strip() for line in f if line.strip()]
    except FileNotFoundError:
        print(f"IP list file not found: {args.ip_list}")
        return
    
    print(f"Loaded {len(ip_list)} IPs to scan for {args.service}")
    
    # Determine ports to scan
    ports = '22' if args.service.lower() == 'ssh' else '3389'
    
    # Send start notification
    start_msg = (
        f"🔍 <b>IP Scan Started</b> 🔍\n\n"
        f"<b>Service:</b> {args.service.upper()}\n"
        f"<b>Total IPs:</b> {len(ip_list)}\n"
        f"<b>Port:</b> {ports}\n"
        f"<b>Start time:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )
    send_telegram_message(args.bot_token, args.chat_id, start_msg)
    
    # Step 1: Masscan for quick port scanning
    print("Starting masscan...")
    masscan_results = masscan_ips(ip_list, ports, timeout=args.timeout)
    print(f"Masscan found {len(masscan_results)} IPs with open ports")
    
    # Step 2: Verify services are actually running
    print("Verifying services...")
    verified_ips = []
    
    with ThreadPoolExecutor(max_workers=args.max_workers) as executor:
        # Create verification tasks
        future_to_ip = {}
        for result in masscan_results:
            future = executor.submit(
                verify_service, 
                result['ip'], 
                result['port'], 
                args.service, 
                args.timeout
            )
            future_to_ip[future] = result['ip']
        
        # Process results as they complete
        for future in as_completed(future_to_ip):
            ip = future_to_ip[future]
            try:
                if future.result():
                    verified_ips.append(ip)
                    print(f"✓ Verified: {ip}")
                else:
                    print(f"✗ Failed verification: {ip}")
            except Exception as e:
                print(f"Error verifying {ip}: {e}")
    
    # Save results
    with open('up_ips.txt', 'w') as f:
        for ip in verified_ips:
            f.write(f"{ip}\n")
    
    # Save detailed results
    results_data = {
        'scan_time': datetime.now().isoformat(),
        'service': args.service,
        'total_ips_scanned': len(ip_list),
        'ips_with_open_ports': len(masscan_results),
        'verified_ips': len(verified_ips),
        'verified_ips_list': verified_ips
    }
    
    with open('scan_results.json', 'w') as f:
        json.dump(results_data, f, indent=2)
    
    # Send results via Telegram
    results_msg = (
        f"✅ <b>Scan Completed</b> ✅\n\n"
        f"<b>Service:</b> {args.service.upper()}\n"
        f"<b>Total IPs scanned:</b> {len(ip_list)}\n"
        f"<b>IPs with open ports:</b> {len(masscan_results)}\n"
        f"<b>Verified running {args.service}:</b> {len(verified_ips)}\n"
        f"<b>Completion time:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        f"<b>Verified IPs:</b>\n" + '\n'.join(verified_ips[:20])
    )
    
    if len(verified_ips) > 20:
        results_msg += f"\n\n...and {len(verified_ips) - 20} more"
    
    send_telegram_message(args.bot_token, args.chat_id, results_msg)
    
    # Also send the IP list as a file if there are results
    if verified_ips:
        try:
            # Send file content as message (Telegram has file size limits)
            file_content = '\n'.join(verified_ips)
            if len(file_content) < 4000:  # Telegram message limit
                file_msg = f"📄 <b>Verified IP List:</b>\n<code>{file_content}</code>"
                send_telegram_message(args.bot_token, args.chat_id, file_msg)
        except Exception as e:
            print(f"Error sending file content: {e}")
    
    print(f"Scan completed! Found {len(verified_ips)} verified IPs")
    print(f"Results saved to: up_ips.txt and scan_results.json")

if __name__ == "__main__":
    main()
