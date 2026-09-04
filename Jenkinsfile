pipeline {
    agent any

    stages {
        stage('1. Checkout') {
            steps {
                echo 'Proje kodları GitHub deposundan çekiliyor...'
                checkout scm
            }
        }

        stage('2. Build Images') {
            steps {
                echo 'Docker Compose ile imajlar inşa ediliyor...'
                sh '''
                    cd strangler-lab
                    docker compose build
                '''
            }
        }

        stage('3. Run Stack') {
            steps {
                echo 'Konteynerler ayağa kaldırılıyor...'
                sh '''
                    cd strangler-lab
                    docker compose up -d
                '''
            }
        }

        stage('4. Health & Smoke Test') {
            steps {
                echo 'Sistemin ayağa kalkması ve sağlık kontrolleri bekleniyor...'
                sh '''
                    sleep 20
                    cd strangler-lab
                    docker compose ps
                '''
                echo 'Sağlık kapısı (/health/) test ediliyor...'
                sh '''
                    STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/health/ || true)
                    echo "HTTP Yanıt Kodu: $STATUS"
                    if [ "$STATUS" != "200" ]; then
                        echo "HATA: Sistem sağlıklı yanıt vermedi!"
                        exit 1
                    fi
                    echo "BAŞARILI: Sistem sağlıklı ve erişilebilir!"
                '''
            }
        }
    }

    post {
        always {
            echo 'Pipeline tamamlandı, test ortamı temizleniyor...'
            sh '''
                cd strangler-lab
                docker compose down
            '''
        }
        success {
            echo 'Tebrikler! Jenkins CI/CD pipeline başarıyla tamamlandı.'
        }
        failure {
            echo 'Pipeline bir adımda hata verdi, lütfen logları kontrol edin.'
        }
    }
}