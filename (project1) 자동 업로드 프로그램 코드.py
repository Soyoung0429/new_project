# "{}" 안의 값은 변경하여 사용
# 라이브러리 가져오기
import os
import sys
import json
import time
import threading
from datetime import datetime, timedelta

import customtkinter as ctk
import tkinter as tk
from tkinter import messagebox
from tkcalendar import DateEntry
from datetime import datetime, timedelta
import threading

import pandas as pd
import psutil
import pyperclip

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    ElementClickInterceptedException,
    TimeoutException,
)

import gspread
from google.oauth2.service_account import Credentials

# 로그인/비밀번호 저장 위치 설정
def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)

CONFIG_FILE = resource_path("config.json")

# 로그인 정보 저장
def save_login(user_id, user_pw, keep_login):
    if keep_login:
        data = {
            "user_id": user_id,
            "user_pw": user_pw,
            "keep_login": True
        }
    else:
        data = {
            "user_id": "",
            "user_pw": "",
            "keep_login": False
        }

    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)

# 로그인 정보 불러오기
def load_login():
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

    data.setdefault("user_id", "")
    data.setdefault("user_pw", "")
    data.setdefault("keep_login", False)
    return data

# 크롤링 결과값 업로드 함수
def run_crawling(user_id, user_pw, start_date, end_date):
    
    # 스프레드시트 값 가져오기
    start_date = pd.to_datetime(start_date)
    end_date = pd.to_datetime(end_date)

    SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
    SERVICE_ACCOUNT_FILE = resource_path("{json 파일명}") # 구글 api 사용을 위해 필요한 json 키 값

    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    gc = gspread.authorize(creds)
    spreadsheet = gc.open_by_url("{스프레드시트 주소}") # 업로드용 글이 있는 장소
    worksheet = spreadsheet.worksheet("{스프레드시트 셀 이름}")  

    data = worksheet.get_all_values()
    df = pd.DataFrame(data[1:], columns=data[0])
    df["날짜"] = pd.to_datetime(df["날짜"], errors="coerce")
    translated_df = df[df["날짜"].between(start_date, end_date)]

    # 사용자 설정
    NAVER_ID = user_id 
    NAVER_PW = user_pw  
    PROFILE_PATH = r"C:/Selenium/Profiles/naver"
    START_MAXIMIZED = True

    # 프로세스/드라이버 유틸
    def kill_chrome_profile(profile_path: str) -> int:
        killed = 0
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                name = (proc.info.get('name') or '').lower()
                if 'chrome' in name:
                    cmdline = proc.info.get('cmdline') or []
                    cmd = " ".join(cmdline)
                    if f'--user-data-dir={profile_path}' in cmd:
                        proc.kill()
                        killed += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied, KeyError):
                continue
        return killed

    def make_driver():
        options = Options()
        options.add_argument(f"--user-data-dir={PROFILE_PATH}")
        if START_MAXIMIZED:
            options.add_argument("--start-maximized")
        driver = webdriver.Chrome(options=options)
        driver.implicitly_wait(0)
        return driver

    def safe_click(el, driver):
        try:
            el.click()
        except ElementClickInterceptedException:
            driver.execute_script("arguments[0].click();", el)

    def type_with_actions(driver, text: str, per_char_delay: float = 0.03):
        actions = ActionChains(driver)
        BATCH = 40
        count = 0
        for ch in str(text):
            actions.send_keys(ch).pause(per_char_delay)
            count += 1
            if count >= BATCH:
                actions.perform()
                actions = ActionChains(driver)
                count = 0
        if count:
            actions.perform()

    def find_first(driver, selectors):
        for sel in selectors:
            try:
                elems = driver.find_elements(By.CSS_SELECTOR, sel)
            except Exception:
                elems = []
            if elems:
                return elems[0]
        return None

    def set_clipboard(id_pw, text: str):
        try:
            pyperclip.copy(text)
            id_pw.send_keys(Keys.CONTROL, 'v')
        except Exception:
            try:
                import tkinter as tk
                r = tk.Tk(); r.withdraw()
                r.clipboard_clear(); r.clipboard_append(text)
                r.update(); r.destroy()
            except Exception as e:
                raise RuntimeError(f"클립보드 설정 실패: {e}")

    def clear_clipboard():
        try:
            pyperclip.copy("")
        except Exception:
            try:
                import tkinter as tk
                r = tk.Tk(); r.withdraw()
                r.clipboard_clear(); r.update(); r.destroy()
            except Exception:
                pass

    def paste_via_ctrl_v(driver):
        actions = ActionChains(driver)
        actions.key_down(Keys.CONTROL).send_keys('v').key_up(Keys.CONTROL).perform()

    # 로그인 확인
    LOGIN_POSSIBLE_HOST_SNIPPETS = (
        "nid.naver.com/nidlogin.login",
        "nid.naver.com/login",
        "nidlogin.login",
    )

    def has_naver_login_cookies(driver) -> bool:
        try:
            return bool(driver.get_cookie("NID_AUT") or driver.get_cookie("NID_SES"))
        except Exception:
            return False

    def left_login_page(driver) -> bool:
        cur = (driver.current_url or "").lower()
        return not any(snippet in cur for snippet in LOGIN_POSSIBLE_HOST_SNIPPETS)

    def gnb_logged_in_visible(driver) -> bool:
        sel = "a#gnbMyPage, .gnb_my_name, #NM_FAVORITE, a#gnb_logout_button, #minime"
        try:
            return len(driver.find_elements(By.CSS_SELECTOR, sel)) > 0
        except Exception:
            return False

    def robust_login_check(driver, wait, total_timeout=25) -> bool:
        end = time.time() + total_timeout
        try:
            WebDriverWait(driver, min(10, total_timeout)).until(
                lambda d: left_login_page(d) or has_naver_login_cookies(d)
            )
        except TimeoutException:
            pass
        if has_naver_login_cookies(driver):
            return True
        if left_login_page(driver):
            try:
                WebDriverWait(driver, 5).until(lambda d: has_naver_login_cookies(d))
                return True
            except TimeoutException:
                pass
        driver.get("https://www.naver.com/")
        try:
            wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
        except TimeoutException:
            pass
        try:
            WebDriverWait(driver, max(1, int(end - time.time()))).until(
                lambda d: gnb_logged_in_visible(d) or has_naver_login_cookies(d)
            )
        except TimeoutException:
            return False
        return gnb_logged_in_visible(driver) or has_naver_login_cookies(driver)
    
    def is_second_auth_page(driver) -> bool:
        url = (driver.current_url or "").lower()
        return any(keyword in url for keyword in [
            "2fa",             
            "2step",          
            "login/ext/otp",    
            "nid.naver.com/login/2",  
            "nidlogin.login?svctype=" #
        ])

    # 로그인 실행
    def login_with_clipboard(driver, wait, user_id: str, user_pw: str, timeout=20) -> bool:
        driver.get("https://nid.naver.com/nidlogin.login?mode=form")
        wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))

        id_selectors = ["#id", "input[name='id']", "input#login-username", "input[type='text']"]
        pw_selectors = ["#pw", "input[name='pw']", "input[type='password']"]
        login_btn_selectors = ["#log\\.login", "button.btn_login", "button[type='submit']"]

        end_time = time.time() + timeout
        id_el = None
        while not id_el and time.time() < end_time:
            id_el = find_first(driver, id_selectors)
            if not id_el:
                time.sleep(0.2)
        if not id_el: raise TimeoutException("아이디 입력란을 찾을 수 없습니다.")
        id_el.click(); set_clipboard(id_el, user_id); clear_clipboard()

        pw_el = None
        while not pw_el and time.time() < end_time:
            pw_el = find_first(driver, pw_selectors)
            if not pw_el:
                time.sleep(0.2)
        if not pw_el: raise TimeoutException("비밀번호 입력란을 찾을 수 없습니다.")
        pw_el.click(); set_clipboard(pw_el, user_pw); clear_clipboard()

        login_btn = find_first(driver, login_btn_selectors)
        if login_btn:
            try: login_btn.click()
            except ElementClickInterceptedException:
                driver.execute_script("arguments[0].click();", login_btn)
        else:
            ActionChains(driver).send_keys(Keys.ENTER).perform()

        clear_clipboard()
        time.sleep(5)
        
        if is_second_auth_page(driver):
            time.sleep(60)
            
        ok = robust_login_check(driver, wait, total_timeout=25)
        if not ok:
            print("⚠️ 로그인 후 확인이 필요합니다. (2단계 인증/캡차 가능, 또는 UI 변경)")
        return ok

    # 블로그 글 작성
    def write_post(driver, wait, NAVER_ID: str, title: str, content: str):
        driver.get(f"https://blog.naver.com/{NAVER_ID}?Redirect=Write&")
        wait.until(EC.any_of(
            EC.url_contains("Redirect=Write"),
            EC.presence_of_element_located((By.CSS_SELECTOR, "iframe, #editor-root, .se-viewer"))
        ))
        time.sleep(1.0)

        wait.until(EC.frame_to_be_available_and_switch_to_it((By.CSS_SELECTOR, "#mainFrame")))

        for sel in [".se-popup-button-cancel", ".se-help-panel-close-button", ".se-popup-button-close"]:
            elems = driver.find_elements(By.CSS_SELECTOR, sel)
            if elems:
                safe_click(elems[0], driver)

        title_candidates = [
            ".se-section-documentTitle",
            "div[contenteditable='true'][placeholder*='제목']",
            "div.se_title"
        ]
        title_el = None
        for sel in title_candidates:
            els = driver.find_elements(By.CSS_SELECTOR, sel)
            if els:
                title_el = els[0]; break
        if not title_el: title_el = driver.switch_to.active_element
        safe_click(title_el, driver)
        type_with_actions(driver, title or "", per_char_delay=0.02)

        body_candidates = [
            ".se-section-text",
            "div[contenteditable='true'][data-placeholder*='내용']",
            "div[contenteditable='true']"
        ]
        body_el = None
        for sel in body_candidates:
            els = driver.find_elements(By.CSS_SELECTOR, sel)
            if els:
                body_el = els[0]; break
        if not body_el: body_el = driver.switch_to.active_element
        safe_click(body_el, driver)
        type_with_actions(driver, content or "", per_char_delay=0.02)
        ActionChains(driver).send_keys(Keys.ENTER).pause(0.02).perform()

        save_selectors = [
            "button[aria-label*='저장']",
            ".save_btn__bzc5B",
            ".se-popup-button-save"
        ]
        save_btn = None
        for sel in save_selectors:
            try:
                save_btn = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.CSS_SELECTOR, ".save_btn__bzc5B")))
                if save_btn: break
            except TimeoutException:
                continue
        if save_btn:
            safe_click(save_btn, driver)
            try:
                WebDriverWait(driver, 10).until(
                    EC.any_of(
                        EC.presence_of_element_located((By.XPATH, "//*[contains(text(),'저장') or contains(text(),'완료')]")),
                        EC.presence_of_element_located((By.CSS_SELECTOR, "[role='status'], .se-toast, .Toastify__toast"))
                    )
                )
                print("임시 저장 완료")
            except TimeoutException:
                print("저장 확인 요소를 찾지 못했습니다. UI가 변경되었을 수 있습니다.")
        else:
            print("⚠️ 저장 버튼을 찾지 못했습니다. 선택자를 갱신하세요.")

        try:
            driver.switch_to.default_content()
        except Exception:
            pass

    # 업로드 함수
    def write_posts_from_df(driver, wait, NAVER_ID: str, df, start_idx: int = 0, end_idx: int | None = None,
                            delay_between: float = 1.0, drop_duplicates: bool = True):
        if not {"제목", "내용"}.issubset(df.columns):
            raise ValueError("df에 '제목', '내용' 컬럼이 필요합니다.")

        work = df.copy()

        work["제목"] = work["제목"].fillna("").astype(str).str.strip()
        work["내용"] = work["내용"].fillna("").astype(str).str.strip()
        
        ban_title = "⚠ 클래스 변경 가능성"
        work = work[~work["제목"].eq(ban_title)]
        
        work = work[(work["제목"] != "") & (work["내용"] != "")]
        if drop_duplicates:
            work = work.drop_duplicates(subset=["제목", "내용"]).reset_index(drop=True)

        rows = work.iloc[start_idx:end_idx] if end_idx is not None else work.iloc[start_idx:]

        print(f"총 {len(rows)}개 포스트 업로드")
        for i, row in rows.reset_index(drop=True).iterrows():
            title, content = row["제목"], row["내용"]
            try:
                print(f"[{i+1}/{len(rows)}] 업로드 중: 제목: '{title}'")
                write_post(driver, wait, NAVER_ID, title, content)
                time.sleep(delay_between)
            except Exception as e:
                print(f"업로드 실패 (index={i}): {repr(e)}")
                try:
                    driver.switch_to.default_content()
                except Exception:
                    pass

    # 실행
    killed = kill_chrome_profile(PROFILE_PATH)
    if killed:
        print(f"정리된 Chrome 프로세스: {killed}개")
    time.sleep(1.0)

    driver = make_driver()
    wait = WebDriverWait(driver, 20)

    try:
        logged_in = login_with_clipboard(driver, wait, NAVER_ID, NAVER_PW)
        if not logged_in:
            raise RuntimeError("로그인 성공을 확인하지 못했습니다. (2단계 인증/캡차/네트워크/쿠키 차단 가능)")

        write_posts_from_df(driver, wait, NAVER_ID, translated_df,
                            start_idx=0,     
                            end_idx=None,     
                            delay_between=1.0 
                            )

    except Exception as e:
        print("에러 발생:", repr(e))
    finally:
        driver.quit()
    messagebox.showinfo("완료", "크롤링이 완료되었습니다!")

# GUI 실행 함수
def create_gui():
    ctk.set_appearance_mode("light")
    ctk.set_default_color_theme("green")

    ACCENT = "#059443"
    ACCENT_DARK = "#005727"
    BG_COLOR = "#e9f5ef"

    root = ctk.CTk()
    root.title("네이버 블로그 자동 업로드")
    root.configure(bg=BG_COLOR)
    root.resizable(False, False)

    empty_icon = tk.PhotoImage(width=1, height=1)
    root.iconphoto(False, empty_icon)
    root._icon = empty_icon

    base_font = ctk.CTkFont(family="Malgun Gothic", size=12)
    header_title_font = ctk.CTkFont(family="Malgun Gothic", size=20, weight="bold") 
    header_sub_font = ctk.CTkFont(family="Malgun Gothic", size=12)                  
    section_font = ctk.CTkFont(family="Malgun Gothic", size=14, weight="bold")
    small_font = ctk.CTkFont(family="Malgun Gothic", size=10)
    button_font = ctk.CTkFont(family="Malgun Gothic", size=14, weight="bold")        
    date_font = ("Malgun Gothic", 9)                                                

    # 바로 root 안에 카드 넣어서 바깥 여백 최소화
    root.rowconfigure(0, weight=1)
    root.columnconfigure(0, weight=1)

    card = ctk.CTkFrame(
        root,
        fg_color="white",
        corner_radius=16,
    )
    # 여백을 아주 조금만 줌 (4px 정도)
    card.grid(row=0, column=0, sticky="nsew", padx=4, pady=4)
    card.columnconfigure(0, weight=1)

    header = ctk.CTkFrame(
        card,
        fg_color=ACCENT,
        corner_radius=16,
    )
    header.grid(row=0, column=0, sticky="ew")
    header.grid_columnconfigure(0, weight=1)

    title_label = ctk.CTkLabel(
        header,
        text="네이버 블로그 자동 업로드",
        font=header_title_font,
        text_color="white",
        anchor="w",
    )
    title_label.grid(row=0, column=0, sticky="ew", padx=24, pady=(18, 2))

    sub_label = ctk.CTkLabel(
        header,
        text="외신 번역본을 네이버 블로그에 자동으로 업로드합니다.",
        font=header_sub_font,
        text_color="#e6fff2",
        anchor="w",
    )
    sub_label.grid(row=1, column=0, sticky="ew", padx=24, pady=(4, 18))

    content = ctk.CTkFrame(card, fg_color="white")
    content.grid(row=1, column=0, sticky="nsew", padx=24, pady=(12, 20))
    content.columnconfigure(0, weight=1)

    sep_top = ctk.CTkFrame(content, fg_color="#e5e7eb", height=1)
    sep_top.grid(row=0, column=0, sticky="ew", pady=(0, 12))
    sep_top.grid_propagate(False)

    login_frame = ctk.CTkFrame(content, fg_color="white")
    login_frame.grid(row=1, column=0, sticky="ew")
    login_frame.columnconfigure(1, weight=1)

    config = load_login()
    yesterday = (datetime.now() - timedelta(days=1)).date()
    keep_login_var = ctk.BooleanVar(value=config.get("keep_login", False))

    row = 0

    ctk.CTkLabel(
        login_frame,
        text="네이버 아이디",
        font=base_font,
        anchor="w",
        text_color="black",
    ).grid(row=row, column=0, sticky="w", pady=(0, 4), padx=(0, 14))

    entry_id = ctk.CTkEntry(
        login_frame,
        font=base_font,
        width=280,
        height=34,
        placeholder_text="example@naver.com",
    )
    entry_id.grid(row=row, column=1, sticky="ew", pady=(0, 4))
    entry_id.insert(0, config.get("user_id", ""))
    row += 1

    ctk.CTkLabel(
        login_frame,
        text="네이버 비밀번호",
        font=base_font,
        anchor="w",
        text_color="black",
    ).grid(row=row, column=0, sticky="w", pady=(8, 4), padx=(0, 14))

    entry_pw = ctk.CTkEntry(
        login_frame,
        font=base_font,
        show="*",
        width=280,
        height=34,
        placeholder_text="비밀번호를 입력하세요",
    )
    entry_pw.grid(row=row, column=1, sticky="ew", pady=(8, 4))
    entry_pw.insert(0, config.get("user_pw", ""))
    row += 1

    keep_check = ctk.CTkCheckBox(
        login_frame,
        text="로그인 상태 유지 (아이디/비밀번호 저장)",
        font=base_font,
        variable=keep_login_var,
        fg_color=ACCENT,
        border_color=ACCENT,
        hover_color=ACCENT_DARK,
    )
    keep_check.grid(row=row, column=0, columnspan=2, sticky="w", pady=(8, 2))
    row += 1

    sep_mid = ctk.CTkFrame(content, fg_color="#e5e7eb", height=1)
    sep_mid.grid(row=2, column=0, sticky="ew", pady=(14, 10))
    sep_mid.grid_propagate(False)

    date_frame = ctk.CTkFrame(content, fg_color="white")
    date_frame.grid(row=3, column=0, sticky="ew")
    date_frame.columnconfigure(1, weight=1)

    ctk.CTkLabel(
        date_frame,
        text="📅 게시물 기간 (YYYY-MM-DD)",
        font=section_font,
        anchor="w",
        text_color="black",
    ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))
    
    naver_calendar_style = {
    "date_pattern": "yyyy-MM-dd",
    "font": ("Malgun Gothic", 9),   
    "background": "#ffffff",        
    "foreground": "#111111",      
    "bordercolor": "#d4d4d4",       
    "normalbackground": "#ffffff",  
    "normalforeground": "#111111",  
    "headersbackground": "#ffffff", 
    "headersforeground": "#666666", 
    "weekendbackground": "#f3f6f4", 
    "weekendforeground": "#111111",
    "othermonthbackground": "#f5f5f5",  
    "othermonthforeground": "#b0b0b0",
    "selectbackground": ACCENT,     
    "selectforeground": "white",    
    "disabledbackground": "#f0f0f0",
    "disabledforeground": "#a0a0a0",
    }
    
    ctk.CTkLabel(
        date_frame,
        text="시작 날짜",
        font=base_font,
        anchor="w",
        text_color="black",
    ).grid(row=1, column=0, sticky="w", pady=(0, 4))

    start_date = DateEntry(
        date_frame,
        width=18,
        **naver_calendar_style
    )
    start_date.grid(row=1, column=1, sticky="w", pady=(0, 4))
    start_date.set_date(yesterday)

    ctk.CTkLabel(
        date_frame,
        text="종료 날짜",
        font=base_font,
        anchor="w",
        text_color="black",
    ).grid(row=2, column=0, sticky="w", pady=(0, 4))

    end_date = DateEntry(
        date_frame,
        width=18,
        **naver_calendar_style
    )
    end_date.grid(row=2, column=1, sticky="w", pady=(0, 4))
    end_date.set_date(yesterday)

    ctk.CTkLabel(
        date_frame,
        text="* 시작/종료 날짜는 기사 업로드 날짜 기준입니다.",
        font=small_font,
        text_color="#777777",
        anchor="w",
    ).grid(row=3, column=0, columnspan=2, sticky="w", pady=(6, 0))

    button_frame = ctk.CTkFrame(content, fg_color="white")
    button_frame.grid(row=4, column=0, pady=(16, 0), sticky="ew")
    button_frame.columnconfigure(0, weight=1)

    def on_run():
        save_login(
            entry_id.get(),
            entry_pw.get(),
            keep_login_var.get(),
        )

        def run_and_close():
            try:
                run_crawling(
                    entry_id.get(),
                    entry_pw.get(),
                    start_date.get(),
                    end_date.get(),
                )
            except Exception as e:
                messagebox.showerror("오류 발생", f"에러: {e}")
            finally:
                root.after(500, root.destroy)

        threading.Thread(target=run_and_close, daemon=True).start()

    btn_run = ctk.CTkButton(
        button_frame,
        text="업로드 시작",
        font=button_font,
        fg_color=ACCENT,
        hover_color=ACCENT_DARK,
        height=48,
        command=on_run,
    )
    btn_run.grid(row=0, column=0, sticky="ew")

    root.update_idletasks()
    win_w, win_h = 500, 480
    x = (root.winfo_screenwidth() // 2) - (win_w // 2)
    y = (root.winfo_screenheight() // 2) - (win_h // 2)
    root.geometry(f"{win_w}x{win_h}+{x}+{y}")

    root.mainloop()

if __name__ == "__main__":
    create_gui()