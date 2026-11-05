"""自适应桌面工作台；缩放只更新字体与布局，不重建预约状态。"""
import tkinter as tk
from tkinter import ttk, font
from tkinter.scrolledtext import ScrolledText
import weakref
import sys
from app_platform import font_family

BG = '#EDF2F5'
INK = '#183242'
MUTED = '#536977'
ACCENT = '#087F74'


class ScrollArea:
    def __init__(self, parent, ui, minimum=610):
        self.ui, self.minimum = weakref.proxy(ui), minimum
        self.frame = ttk.Frame(parent, style='Shell.TFrame')
        self.frame.rowconfigure(0, weight=1); self.frame.columnconfigure(0, weight=1)
        self.canvas = tk.Canvas(self.frame, background=BG, highlightthickness=0, borderwidth=0)
        self.canvas.grid(row=0, column=0, sticky='nsew')
        self.vertical = ttk.Scrollbar(self.frame, orient='vertical', command=self.canvas.yview)
        self.vertical.grid(row=0, column=1, sticky='ns')
        self.horizontal = ttk.Scrollbar(self.frame, orient='horizontal', command=self.canvas.xview)
        self.horizontal.grid(row=1, column=0, sticky='ew')
        self.canvas.configure(yscrollcommand=self.set_y, xscrollcommand=self.set_x)
        self.content = ttk.Frame(self.canvas, style='Shell.TFrame')
        self.item = self.canvas.create_window((0, 0), window=self.content, anchor='nw')
        self.on_resize = None
        self.canvas.bind('<Configure>', self.resize)
        self.content.bind('<Configure>', self.sync)
        parent.winfo_toplevel().bind('<MouseWheel>', self.wheel, add='+')

    def set_y(self, low, high):
        self.vertical.set(low, high)
        if float(low)>0 or float(high)<0.999:
            self.vertical.grid()
        else: self.vertical.grid_remove()

    def set_x(self, low, high):
        self.horizontal.set(low, high)
        if float(low)>0 or float(high)<0.999:
            self.horizontal.grid()
        else: self.horizontal.grid_remove()

    def resize(self, event=None):
        width = max(self.canvas.winfo_width(), self.ui.p(self.minimum))
        if self.on_resize: self.on_resize(width / self.ui.scale)
        self.canvas.itemconfigure(self.item, width=width, height=max(self.canvas.winfo_height(), self.content.winfo_reqheight()))
        self.canvas.configure(scrollregion=self.canvas.bbox('all'))

    def sync(self, event=None):
        self.canvas.configure(scrollregion=self.canvas.bbox('all'))
        desired = max(self.canvas.winfo_height(), self.content.winfo_reqheight())
        if int(float(self.canvas.itemcget(self.item, 'height'))) != desired:
            self.canvas.itemconfigure(self.item, height=desired)

    def wheel(self, event):
        if event.widget.winfo_class() in ('Listbox', 'Text', 'TCombobox'): return
        steps=-int(event.delta/120) if abs(event.delta)>=120 else -int(event.delta)
        self.canvas.yview_scroll(steps, 'units')


class WorkspaceView:
    def __init__(self, app):
        self.app, self.root = weakref.proxy(app), app.root
        self.inputs = []
        self.input_states = {}
        self.system_scale = getattr(self.root, '_system_dpi', self.root.winfo_fpixels('1i')) / 96
        self.zoom = tk.StringVar(value=app.settings.get('ui_zoom', '100%'))
        if self.zoom.get() not in ('85%', '100%', '115%', '125%', '150%', '175%', '200%'):
            self.zoom.set('100%')
        self.scale = self.system_scale * int(self.zoom.get()[:-1]) / 100
        self.fonts = {name: font.Font(root=self.root, family=font_family(), size=-self.p(size), weight=weight)
                      for name, size, weight in [('body',16,'normal'),('small',13,'normal'),('heading',19,'bold'),('title',30,'bold'),('button',16,'bold'),('list',18,'normal')]}
        self.style = ttk.Style(self.root); self.style.theme_use('clam')
        self.configure_style()
        self.root.title('交大场地助手 · 预约工作台')
        self.root.configure(background=BG)
        self.root.geometry(self.window_geometry(1280, 860))
        self.root.minsize(min(self.p(720), self.root.winfo_screenwidth()-80), min(self.p(580), self.root.winfo_screenheight()-120))
        self.root.columnconfigure(0, weight=1); self.root.rowconfigure(1, weight=1)
        header = ttk.Frame(self.root, style='Hero.TFrame', padding=(self.p(26), self.p(20)))
        header.grid(row=0, column=0, sticky='ew'); header.columnconfigure(0, weight=1)
        ttk.Label(header, text='SJTU  /  SPORTS ASSISTANT', style='Eyebrow.TLabel').grid(row=0, column=0, sticky='w')
        ttk.Label(header, text='场地预约工作台', style='Hero.TLabel').grid(row=1, column=0, sticky='w', pady=(self.p(5), 0))
        zoom_frame = ttk.Frame(header, style='Hero.TFrame'); zoom_frame.grid(row=0, column=1, rowspan=2, sticky='e')
        ttk.Label(zoom_frame, text='界面缩放', style='Eyebrow.TLabel').pack(anchor='e', pady=(0, self.p(5)))
        zoom_box = ttk.Combobox(zoom_frame, textvariable=self.zoom, values=['85%', '100%', '115%', '125%', '150%', '175%', '200%'], state='readonly', width=7,font=self.fonts['body'])
        zoom_box.pack(anchor='e'); zoom_box.bind('<<ComboboxSelected>>', lambda e: self.set_zoom(self.zoom.get()))
        self.area = ScrollArea(self.root, self)
        self.area.frame.grid(row=1, column=0, sticky='nsew', padx=self.p(20), pady=self.p(16))
        body = self.area.content
        self.cards = []
        def card(title, subtitle):
            frame = ttk.Frame(body, style='Card.TFrame', padding=self.p(20))
            ttk.Label(frame, text=title, style='Heading.TLabel').pack(anchor='w')
            ttk.Label(frame, text=subtitle, style='Muted.TLabel').pack(anchor='w', pady=(self.p(4), self.p(14)))
            content = ttk.Frame(frame); content.pack(fill='both', expand=True)
            self.cards.append(frame)
            return content
        target = card('01   预约目标', '先登录校园账号，再读取实时场次')
        for i in range(2): target.columnconfigure(i, weight=1)
        self.field(target, '使用浏览器', app.browser, 0, 0, ['chromium','edge','chrome','firefox','webkit'])
        self.field(target, '预约日期  YYYY-MM-DD', app.day, 0, 1)
        sport_box = self.field(target, '运动项目', app.sport, 2, 0, sorted({e['sport'] for e in app.entries}))
        sport_box.bind('<<ComboboxSelected>>', app.update_venues)
        app.venue_box = self.field(target, '目标场馆', app.venue, 4, 0, [], span=2)
        actions = ttk.Frame(target); actions.grid(row=6, column=0, columnspan=2, sticky='ew', pady=(self.p(14),0))
        actions.columnconfigure((0,1), weight=1)
        app.login_button = ttk.Button(actions, text='登录 / 更新会话', command=lambda: app.dispatch('login'))
        app.login_button.grid(row=0,column=0,sticky='ew',padx=(0,self.p(6)))
        app.load_button = ttk.Button(actions, text='读取场地', command=lambda: app.dispatch('load'))
        app.load_button.grid(row=0,column=1,sticky='ew')
        app.continue_button = ttk.Button(actions, text='认证已完成，继续', command=app.resume.set, state='disabled')
        app.continue_button.grid(row=1,column=0,columnspan=2,sticky='ew',pady=(self.p(8),0))
        selection = card('02   场地与时间', '先选择预约方式，再勾选目标时段')
        selection.columnconfigure((0,1), weight=1, uniform='lists'); selection.rowconfigure(3, weight=1)
        boxes = []
        for col, title in enumerate(['场地（多选时任选一块）', '目标时段（可多选）']):
            ttk.Label(selection,text=title,style='Muted.TLabel').grid(row=2,column=col,sticky='w',pady=(self.p(12),self.p(8)))
            holder = ttk.Frame(selection); holder.grid(row=3,column=col,sticky='nsew',padx=(0,self.p(10) if col==0 else 0))
            box = tk.Listbox(holder, selectmode='multiple',exportselection=False,height=6,width=12,font=self.fonts['list'],
                             background='#F3F7F8',foreground=INK,selectbackground='#C8EAE3',selectforeground='#075D55',
                             relief='flat',borderwidth=0,highlightthickness=1,highlightbackground='#DFE8EC',highlightcolor=ACCENT,activestyle='dotbox')
            box.pack(side='left',fill='both',expand=True)
            scroll=ttk.Scrollbar(holder,command=box.yview);scroll.pack(side='right',fill='y');box.configure(yscrollcommand=scroll.set)
            boxes.append(box)
        app.court_list,app.slot_list=boxes
        self.inputs.extend(boxes)
        modes=ttk.Frame(selection);modes.grid(row=0,column=0,columnspan=2,sticky='ew')
        for text,value in [('任选一段 · 所选时段中只要一小时','任选一段'),('连续两段 · 同一场地必须同时满足两小时','连续两段')]:
            radio=ttk.Radiobutton(modes,text=text,variable=app.time_mode,value=value)
            radio.pack(anchor='w',pady=self.p(3));self.inputs.append(radio)
        summary=ttk.Label(selection,textvariable=app.selection_summary,style='Summary.TLabel',wraplength=self.p(440),padding=self.p(10))
        summary.grid(row=1,column=0,columnspan=2,sticky='ew',pady=(self.p(12),0))
        selection.bind('<Configure>',lambda e:summary.configure(wraplength=max(self.p(200),e.width-self.p(24))))
        app.slot_list.bind('<<ListboxSelect>>',app.update_selection_summary)
        app.court_list.bind('<<ListboxSelect>>',app.update_selection_summary)
        app.time_mode.trace_add('write',app.update_selection_summary)
        app.sport.trace_add('write',app.update_selection_summary)
        app.day.trace_add('write',app.update_selection_summary)
        app.venue.trace_add('write',app.update_selection_summary)
        options = card('03   蹲守设置', '保持电脑联网；命中后由你确认并付款')
        options.columnconfigure((0,1),weight=1)
        self.field(options,'检查间隔 / 秒',app.interval,0,0)
        self.field(options,'截止时刻 / HH:MM',app.end,0,1)
        self.field(options,'命中后执行',app.mode,2,0,['自动提交到待支付','仅选中，手动下单'],span=2)
        ttk.Label(options,text='截止留空时，监控到最早目标时段开始。',style='Muted.TLabel').grid(row=4,column=0,columnspan=2,sticky='w',pady=(self.p(6),self.p(12)))
        notice=ttk.Frame(options);notice.grid(row=5,column=0,columnspan=2,sticky='ew')
        ttk.Label(notice,textvariable=app.binding_status,style='Muted.TLabel').pack(anchor='w')
        app.binding_button=ttk.Button(notice,text='绑定微信通知',command=app.bind_notice)
        app.binding_button.pack(anchor='w',pady=(self.p(8),0))
        activity = card('运行记录', '登录、读取与蹲守进度会显示在这里')
        app.log=ScrolledText(activity,height=6,width=20,state='disabled',font=self.fonts['body'],background='#102B3B',foreground='#D8E8ED',
                             relief='flat',borderwidth=0,padx=self.p(14),pady=self.p(12),insertbackground='white')
        app.log.pack(fill='both',expand=True)
        footer=ttk.Frame(self.root,padding=(self.p(24),self.p(12)))
        self.footer=footer
        footer.grid(row=2,column=0,sticky='ew');footer.columnconfigure(0,weight=1)
        self.status_label=ttk.Label(footer,textvariable=app.status,style='Status.TLabel',wraplength=self.p(660))
        self.status_label.grid(row=0,column=0,columnspan=3,sticky='ew',pady=(0,self.p(10)))
        self.legacy_button=ttk.Button(footer,text='原定时抢场 / 演练',command=app.legacy)
        self.stop_button=ttk.Button(footer,text='停止监控',command=app.cancel)
        app.start_button=ttk.Button(footer,text='开始蹲场地  →',style='Primary.TButton',command=lambda:app.dispatch('watch'))
        app.start_button.grid(row=1,column=2,sticky='e')
        self.layout_mode=None
        view_ref=weakref.ref(self)
        self.area.on_resize=lambda width: view_ref().responsive(width) if view_ref() else None
        self.root.bind('<Control-plus>',lambda e:self.step_zoom(1))
        self.root.bind('<Control-equal>',lambda e:self.step_zoom(1))
        self.root.bind('<Control-minus>',lambda e:self.step_zoom(-1))
        self.root.bind('<Control-0>',lambda e:self.set_zoom('100%'))
        if sys.platform=='darwin':
            self.root.bind('<Command-plus>',lambda e:self.step_zoom(1))
            self.root.bind('<Command-equal>',lambda e:self.step_zoom(1))
            self.root.bind('<Command-minus>',lambda e:self.step_zoom(-1))
            self.root.bind('<Command-0>',lambda e:self.set_zoom('100%'))
        app.update_venues();app.refresh_binding_status()
        self.responsive(1280)

    def p(self,value): return max(1,round(value*self.scale))

    def window_geometry(self,w,h):
        return f'{min(self.p(w),self.root.winfo_screenwidth()-self.p(40))}x{min(self.p(h),self.root.winfo_screenheight()-self.p(65))}'

    def field(self,parent,label,variable,row,col,values=None,span=1):
        padx=(0,self.p(10)) if col==0 and span==1 else (0,0)
        ttk.Label(parent,text=label,style='Muted.TLabel').grid(row=row,column=col,columnspan=span,sticky='w',padx=padx,pady=(self.p(6),self.p(6)))
        entry=ttk.Entry(parent,textvariable=variable,width=14,font=self.fonts['body']) if values is None else ttk.Combobox(parent,textvariable=variable,values=values,state='readonly',width=14,font=self.fonts['body'])
        entry.grid(row=row+1,column=col,columnspan=span,sticky='ew',padx=padx,pady=(0,self.p(6)))
        self.inputs.append(entry)
        return entry

    def set_busy(self, busy):
        if busy:
            self.input_states={widget:str(widget['state']) for widget in self.inputs}
            for widget in self.inputs:widget.configure(state='disabled')
        else:
            for widget,state in self.input_states.items():widget.configure(state=state)
            self.input_states={}
            if self.app.loaded_identity and not self.app.courts:self.app.court_list.configure(state='disabled')

    def configure_style(self):
        s=self.style
        s.configure('.',font=self.fonts['body'],background='white',foreground=INK)
        s.configure('TFrame',background='white')
        s.configure('Shell.TFrame',background=BG)
        s.configure('Card.TFrame',background='white',relief='flat')
        s.configure('Hero.TFrame',background='#102B3B')
        s.configure('TLabel',background='white',foreground=INK)
        s.configure('Muted.TLabel',font=self.fonts['small'],foreground=MUTED)
        s.configure('Heading.TLabel',font=self.fonts['heading'])
        s.configure('Hero.TLabel',font=self.fonts['title'],background='#102B3B',foreground='white')
        s.configure('Eyebrow.TLabel',font=self.fonts['small'],background='#102B3B',foreground='#B8D2D8')
        # 兼容通知绑定窗口的共享样式。
        s.configure('Shell.TLabel',background=BG,foreground=MUTED)
        s.configure('Title.TLabel',font=self.fonts['heading'],background=BG,foreground=INK)
        s.configure('Status.TLabel',font=self.fonts['body'],foreground='#075D55')
        s.configure('Summary.TLabel',font=self.fonts['small'],background='#E8F4F1',foreground='#075D55')
        s.configure('TLabelframe',background='white',bordercolor='#D8E4E9',relief='solid',borderwidth=1)
        s.configure('TLabelframe.Label',font=self.fonts['heading'],background=BG,foreground=INK)
        s.configure('TButton',font=self.fonts['body'],padding=(self.p(14),self.p(10)),background='#E6EEF0',foreground=INK,borderwidth=0)
        s.map('TButton',background=[('active','#D6E4E7'),('disabled','#EDF2F4')],foreground=[('disabled','#8B9BA6')])
        s.configure('Primary.TButton',font=self.fonts['button'],background=ACCENT,foreground='white')
        s.map('Primary.TButton',background=[('active','#066B62'),('disabled','#91BCB6')],foreground=[('disabled','white')])
        s.configure('TEntry',font=self.fonts['body'],padding=self.p(8),fieldbackground='#F4F7F8',bordercolor='#DCE6EA')
        s.configure('TCombobox',font=self.fonts['body'],padding=self.p(8),fieldbackground='#F4F7F8',bordercolor='#DCE6EA',arrowsize=self.p(14))
        s.map('TCombobox',fieldbackground=[('readonly','#F4F7F8')],foreground=[('readonly',INK)])
        s.configure('TCheckbutton',font=self.fonts['body'],padding=self.p(4))
        s.configure('TRadiobutton',font=self.fonts['body'],padding=self.p(4))
        s.configure('TScrollbar',arrowsize=self.p(14),width=self.p(14),background='#CCDADF',troughcolor=BG,borderwidth=0)
        for direction,sticky in [('Vertical','ns'),('Horizontal','ew')]:
            s.layout(direction+'.TScrollbar',[(direction+'.Scrollbar.trough',{'sticky':sticky,'children':[(direction+'.Scrollbar.thumb',{'expand':'1','sticky':'nsew'})]})])
            s.configure(direction+'.TScrollbar',background='#BCCFD5',troughcolor=BG,bordercolor=BG,lightcolor='#BCCFD5',darkcolor='#BCCFD5',borderwidth=0,width=self.p(10))
        self.root.option_add('*TCombobox*Listbox.font',self.fonts['body'])

    def responsive(self,width):
        compact=self.root.winfo_width()/self.scale<900
        for button in (self.legacy_button,self.stop_button,self.app.start_button):button.grid_forget()
        if compact:
            self.stop_button.grid(row=1,column=0,sticky='w')
            self.app.start_button.grid(row=1,column=1,columnspan=2,sticky='e')
            self.legacy_button.grid(row=2,column=0,columnspan=3,sticky='ew',pady=(self.p(8),0))
        else:
            self.legacy_button.grid(row=1,column=0,sticky='w')
            self.stop_button.grid(row=1,column=1,padx=self.p(10))
            self.app.start_button.grid(row=1,column=2,sticky='e')
        self.status_label.configure(wraplength=max(self.p(250),self.root.winfo_width()-self.p(50)))
        mode='wide' if width>=1050 else 'stacked'
        if mode==self.layout_mode:return
        self.layout_mode=mode
        body=self.area.content
        for card in self.cards:card.grid_forget()
        body.columnconfigure(0,weight=4);body.columnconfigure(1,weight=5 if mode=='wide' else 0)
        for i in range(4):body.rowconfigure(i,weight=0)
        if mode=='wide':
            for i,card in enumerate(self.cards):
                card.grid(row=i//2,column=i%2,sticky='nsew',padx=(0,self.p(14)) if i%2==0 else 0,pady=(0,self.p(14)))
            body.rowconfigure(0,weight=3);body.rowconfigure(1,weight=2)
        else:
            for i,card in enumerate(self.cards):card.grid(row=i,column=0,sticky='nsew',pady=(0,self.p(14)))

    def set_zoom(self,value):
        self.zoom.set(value)
        self.scale=self.system_scale*int(value[:-1])/100
        for name,size in [('body',16),('small',13),('heading',19),('title',30),('button',16),('list',18)]:
            self.fonts[name].configure(size=-self.p(size))
        self.configure_style()
        self.layout_mode=None
        self.area.resize()
        try:
            self.app.save_settings()
        except OSError:
            self.app.status.set('界面已缩放，但设置未保存。请将程序移到可写文件夹。')
        return 'break'

    def step_zoom(self,step):
        values=['85%','100%','115%','125%','150%','175%','200%']
        self.set_zoom(values[max(0,min(len(values)-1,values.index(self.zoom.get())+step))])
        return 'break'
