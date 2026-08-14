"""Package efectividad.

Submodulo para la geeracion de informes de efectividad
"""
class OSTransfersController:
    # Transferencias AS400: ACSBundle
    transferfolder = ""
    currentTransferFile = ""
    _main_dir = ""
    _us_transfer = ""
    _pw_transfer = ""
    
    def __init__(self, 
                 transferFolder="D:/com/jupyter/Procesos/AfiliacionMasiva/Diners/transfer/"
                ):
        self.log = {}
        self.transferfolder = transferFolder
        self.currentTransferFile = ""
        self._main_dir = "D:/com/lab"
        self._us_transfer = _L5rHg47L
        self._pw_transfer = _P4O0NJ2v
        self.set_logger()

    def set_logger(self):
        logging.basicConfig(
            level=logging.DEBUG,
            format='%(asctime)s %(levelname)-8s %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        self.log = logging.getLogger()

    def set_config_transfer(self, filetransfer, configsection,
                            configkey, configvalue):
        """
        Lee los archivos de transferencis AS400 y modifica los
        parametros especificados
        """
        config = configparser.ConfigParser()
        config.optionxform = str # type: ignore
        self.set_current_transfer_filename(filetransfer)
        config.read(self.currentTransferFile)
        self.log.info("Change in section %s[%s]:%s" %
                      (configsection, configkey, configvalue)
                      )
        config.set(configsection, configkey, configvalue)
        with open(self.currentTransferFile, 'w') as cfgfile:
            config.write(cfgfile, False)
    
    def set_current_transfer_filename(self, filetransfer):
        """
        Lee los archivos de transferencis AS400 y modifica los
        parametros especificados
        """
        self.log.info("> Init transfer file: `%s`" % (filetransfer))
        self.currentTransferFile = self.transferfolder + filetransfer
        return self

    def acsbundle_init(self):
        """
        Inicializa la nueva version de transferencia utilizando el programa `acsbundle.jar`
        para realizar las tranferencias del gestor.
        """
        proc = Popen(["java", "-jar", f"{self._main_dir}/.cfg/acsbundle.jar", "/plugin=logon", "/system=AS400F35",
                    f"/userid={self._us_transfer}", f"/password={self._pw_transfer}",
                    "/gui=0"], stdin=PIPE, stdout=PIPE, stderr=PIPE)
        output, err = proc.communicate()
        if err:
            self.log.error(f"{err.decode('utf-8')} in {os.path.realpath(__file__)}")
        for line in output.decode('ISO8859-1').split('\r\n'):
            self.log.info(line)

    def acsbundle_upload(self):
        """
        Realiza la carga de archivos al as400.
        """
        proc = Popen(["java", "-jar", f"{self._main_dir}/.cfg/acsbundle.jar", "/plugin=upload",
                      self.currentTransferFile, f"/userid={self._us_transfer}"],
                      stdin=PIPE, stdout=PIPE, stderr=PIPE)
        output, err = proc.communicate()
        if err:
            self.log.error(err)
        for line in output.decode('ISO8859-1').split('\n'):
            if line.strip()[:6].upper() == "FILAS ":
                rows = line.strip().split(':')[1].strip()
                self.log.info(f"> {rows} rows uploaded")


    def acsbundle_download(self):
        """
        Realiza la descarga de archivos del as400.
        """
        proc = Popen(["java", "-jar", f"{self._main_dir}/.cfg/acsbundle.jar", "/plugin=download",
                      "/system=AS400F35", f"/userid={self._us_transfer}", self.currentTransferFile],
                      stdin=PIPE, stdout=PIPE, stderr=PIPE)
        output, err = proc.communicate()
        if err:
            self.log.error(err)
        for line in output.decode('ISO8859-1').split('\n'):
            if line.strip()[:6].upper() == "FILAS ":
                rows = line.strip().split(':')[1].strip()
                self.log.info(f"> {rows} rows downloaded")



# In[ ]:
class SFTPManager:
    
    client = paramiko.SSHClient()
    default_path = ""
    
    def __init__(self):
        self.client = paramiko.SSHClient()
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.default_path = './LINK MOBILE LINKMBL BTS_ SMS/'

    def getFilesList(self):
        try:
            self.client.connect(
                sftp_host,
                sftp_port,
                sftp_uid,
                sftp_pwd,
                allow_agent=False,
                look_for_keys=False)
            # Abrir sesión SFTP
            sftp = self.client.open_sftp()
            print("Conexión SFTP exitosa")
            # lista archivos disponibles
            files_available = [archivo for archivo in sftp.listdir(self.default_path)]
            return files_available
            sftp.close()
        finally:
            self.client.close()
        
    def downloadSelectedFile(self, selected_filename):
        try:
            print(f"⏳ Iniciando descarga `{selected_filename}`..", end='')
            self.client.connect(
                sftp_host,
                sftp_port,
                sftp_uid,
                sftp_pwd,
                allow_agent=False,
                look_for_keys=False)
            # Abrir sesión SFTP
            sftp = self.client.open_sftp()
            # descarga archivo
            download_file = f"./vendor/{selected_filename}"
            sftp.get(f"{self.default_path}/{selected_filename}", download_file)
            print(f".🗄️comprimiendo..", end='')
            with zipfile.ZipFile(f"{download_file}.zip", "w", zipfile.ZIP_DEFLATED) as zipf:
                zipf.write(download_file, arcname=os.path.basename(download_file))
            print(f". 🟢 finalizado.")
            os.unlink(download_file)
            sftp.close()
        finally:
            self.client.close()
        
    